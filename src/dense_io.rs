//! Single-writer, checksum-bound restart artifacts. POSIX lock is released by
//! process death; commits flush data then rename within the same directory.
use crate::{
    hash::{sha256, Sha256},
    Result,
};
#[cfg(unix)]
use std::os::unix::io::AsRawFd;
use std::{
    fs::{self, File, OpenOptions},
    io::{BufWriter, Read, Write},
    path::{Path, PathBuf},
};
#[cfg(unix)]
extern "C" {
    fn flock(fd: i32, operation: i32) -> i32;
}
pub struct Lock {
    _file: File,
}
impl Lock {
    pub fn acquire(dir: &Path) -> Result<Self> {
        let file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .open(dir.join(".writer.lock"))
            .map_err(|e| e.to_string())?;
        #[cfg(unix)]
        {
            // SAFETY: valid owned file descriptor; LOCK_EX|LOCK_NB is nonblocking.
            if unsafe { flock(file.as_raw_fd(), 2 | 4) } != 0 {
                return Err("another dense writer holds this run lock".into());
            }
            Ok(Self { _file: file })
        }
        #[cfg(not(unix))]
        {
            let _ = file;
            Err("durable dense controller currently requires a POSIX filesystem".into())
        }
    }
}
fn sync_dir(path: &Path) -> Result<()> {
    File::open(path)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())
}
pub struct Writer {
    file: BufWriter<File>,
    hash: Sha256,
    temp: PathBuf,
    path: PathBuf,
    pub bytes: u64,
}
impl Writer {
    pub fn new(path: &Path) -> Result<Self> {
        if path.exists() {
            return Err(format!(
                "immutable artifact already exists: {}",
                path.display()
            ));
        }
        let temp = path.with_extension("pending");
        // The caller owns the directory lock; a killed writer's staging file has
        // no commit marker and is deliberately overwritten, never counted complete.
        let f = File::create(&temp).map_err(|e| e.to_string())?;
        Ok(Self {
            file: BufWriter::new(f),
            hash: Sha256::default(),
            temp,
            path: path.to_path_buf(),
            bytes: 0,
        })
    }
    pub fn write(&mut self, b: &[u8]) -> Result<()> {
        self.file.write_all(b).map_err(|e| e.to_string())?;
        self.hash.update(b);
        self.bytes = self
            .bytes
            .checked_add(b.len() as u64)
            .ok_or("artifact byte overflow")?;
        Ok(())
    }
    pub fn finish(mut self) -> Result<String> {
        let h = self.hash.finish();
        self.file
            .write_all(h.as_bytes())
            .map_err(|e| e.to_string())?;
        self.file.flush().map_err(|e| e.to_string())?;
        self.file.get_ref().sync_all().map_err(|e| e.to_string())?;
        fs::rename(&self.temp, &self.path).map_err(|e| e.to_string())?;
        sync_dir(self.path.parent().ok_or("artifact parent")?)?;
        Ok(h)
    }
}
pub fn put(path: &Path, bytes: &[u8]) -> Result<String> {
    let mut w = Writer::new(path)?;
    w.write(bytes)?;
    w.finish()
}
pub fn read(path: &Path, budget: usize) -> Result<Vec<u8>> {
    let size = fs::metadata(path).map_err(|e| e.to_string())?.len();
    if size < 64 || size > (budget as u64).saturating_add(64) {
        return Err("artifact length/budget".into());
    }
    let mut bytes = fs::read(path).map_err(|e| e.to_string())?;
    let n = bytes.len() - 64;
    if sha256(&bytes[..n]).as_bytes() != &bytes[n..] {
        return Err(format!("artifact checksum mismatch: {}", path.display()));
    }
    bytes.truncate(n);
    Ok(bytes)
}
pub fn verify(path: &Path) -> Result<(String, u64)> {
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let n = file.metadata().map_err(|e| e.to_string())?.len();
    if n < 64 {
        return Err("truncated sealed artifact".into());
    }
    let mut rem = n - 64;
    let mut hash = Sha256::default();
    let mut buf = [0u8; 65536];
    while rem > 0 {
        let len = rem.min(buf.len() as u64) as usize;
        file.read_exact(&mut buf[..len])
            .map_err(|e| e.to_string())?;
        hash.update(&buf[..len]);
        rem -= len as u64;
    }
    let mut seal = [0; 64];
    file.read_exact(&mut seal).map_err(|e| e.to_string())?;
    let got = hash.finish();
    if got.as_bytes() != seal {
        return Err(format!("artifact checksum mismatch: {}", path.display()));
    }
    Ok((got, n - 64))
}
pub struct Reader<'a> {
    b: &'a [u8],
    at: usize,
}
impl<'a> Reader<'a> {
    pub fn new(b: &'a [u8]) -> Self {
        Self { b, at: 0 }
    }
    pub fn bytes(&mut self, n: usize) -> Result<&'a [u8]> {
        let end = self.at.checked_add(n).ok_or("decode length overflow")?;
        let v = self.b.get(self.at..end).ok_or("truncated dense artifact")?;
        self.at = end;
        Ok(v)
    }
    pub fn u64(&mut self) -> Result<u64> {
        Ok(u64::from_le_bytes(self.bytes(8)?.try_into().unwrap()))
    }
    pub fn u128(&mut self) -> Result<u128> {
        Ok(u128::from_le_bytes(self.bytes(16)?.try_into().unwrap()))
    }
    pub fn f64(&mut self) -> Result<f64> {
        Ok(f64::from_bits(self.u64()?))
    }
    pub fn end(&self) -> Result<()> {
        if self.at != self.b.len() {
            Err("trailing dense artifact bytes".into())
        } else {
            Ok(())
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lock_checksum_and_uncommitted_staging() {
        let dir = std::env::temp_dir().join(format!("filang-dense-io-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let lock = Lock::acquire(&dir).unwrap();
        assert!(Lock::acquire(&dir).is_err());
        let path = dir.join("test.chk");
        {
            let mut w = Writer::new(&path).unwrap();
            w.write(b"incomplete").unwrap();
        }
        assert!(!path.exists());
        put(&path, b"complete").unwrap();
        assert_eq!(read(&path, 100).unwrap(), b"complete");
        assert!(put(&path, b"overwrite").is_err());
        let mut b = fs::read(&path).unwrap();
        b[0] ^= 1;
        fs::write(&path, b).unwrap();
        assert!(read(&path, 100).is_err());
        assert!(verify(&path).is_err());
        drop(lock);
        let lock = Lock::acquire(&dir).unwrap();
        drop(lock);
        fs::remove_dir_all(dir).unwrap();
    }
}
