//! Exact sample-scoped predicate identities with reconstructible parameter aliases.
use crate::{rules::Mask, Result};
use std::collections::HashMap;
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord)]
pub struct Coordinate {
    pub atom: u64,
    pub qualifier: u64,
    pub cutoff: u64,
}
#[derive(Clone, Debug)]
pub struct Entry {
    pub mask: Mask,
    pub count: u128,
    pub first: Coordinate,
}
pub struct Builder {
    pub entries: Vec<Entry>,
    index: HashMap<u64, Vec<usize>>,
    pub cells: u64,
    pub addresses: u128,
    pub payload: usize,
    budget: usize,
    rows: usize,
}
pub fn key(mask: &Mask) -> u64 {
    mask.bits
        .iter()
        .chain(&mask.valid)
        .fold(mask.len as u64 ^ 0xcbf29ce484222325, |h, v| {
            (h ^ v).wrapping_mul(0x100000001b3)
        })
}
pub fn validate_mask(mask: &Mask, rows: usize) -> Result<()> {
    let n = (rows + 63) / 64;
    if mask.len != rows
        || mask.bits.len() != n
        || mask.valid.len() != n
        || mask.bits.iter().zip(&mask.valid).any(|(b, v)| b & !v != 0)
        || rows % 64 != 0 && n > 0 && (mask.bits[n - 1] | mask.valid[n - 1]) >> (rows % 64) != 0
    {
        return Err("dense predicate mask timeline/validity/tail".into());
    }
    Ok(())
}
impl Builder {
    pub fn new(rows: usize, budget: usize) -> Result<Self> {
        if rows == 0 || budget < 1024 {
            return Err("dense bank nonempty range/budget".into());
        }
        Ok(Self {
            entries: Vec::new(),
            index: HashMap::new(),
            cells: 0,
            addresses: 0,
            payload: 0,
            budget,
            rows,
        })
    }
    pub fn intern(&mut self, mask: &Mask, count: u128, first: Coordinate) -> Result<usize> {
        self.intern_key(mask, count, first, key(mask))
    }
    fn intern_key(
        &mut self,
        mask: &Mask,
        count: u128,
        first: Coordinate,
        hash: u64,
    ) -> Result<usize> {
        validate_mask(mask, self.rows)?;
        if count == 0 {
            return Err("empty alias domain".into());
        }
        let found = self
            .index
            .get(&hash)
            .and_then(|v| v.iter().find(|&&i| self.entries[i].mask == *mask))
            .copied();
        let id = if let Some(i) = found {
            let entry = &mut self.entries[i];
            entry.count = entry
                .count
                .checked_add(count)
                .ok_or("alias count overflow")?;
            entry.first = entry.first.min(first);
            i
        } else {
            let charge = mask
                .payload()
                .checked_add(320)
                .ok_or("bank charge overflow")?;
            let next = self
                .payload
                .checked_add(charge)
                .ok_or("bank payload overflow")?;
            if next > self.budget {
                return Err(
                    "dense predicate bank budget exceeded; partition the preparation domain".into(),
                );
            }
            let id = self.entries.len();
            self.entries.push(Entry {
                mask: mask.clone(),
                count,
                first,
            });
            self.index.entry(hash).or_default().push(id);
            self.payload = next;
            id
        };
        self.cells = self.cells.checked_add(1).ok_or("cell count overflow")?;
        self.addresses = self
            .addresses
            .checked_add(count)
            .ok_or("coverage overflow")?;
        Ok(id)
    }
}

/// Stored state dictionary. Membership coordinates are streamed separately; they
/// are not discarded when two programs agree on this scored sample.
pub fn save(
    entries: &[Entry],
    rows: usize,
    context: &str,
    path: &std::path::Path,
) -> Result<String> {
    if context.len() != 64 {
        return Err("dense bank context digest".into());
    }
    let mut w = crate::dense_io::Writer::new(path)?;
    w.write(b"FDBANK01")?;
    w.write(context.as_bytes())?;
    w.write(&(rows as u64).to_le_bytes())?;
    w.write(&(entries.len() as u64).to_le_bytes())?;
    for e in entries {
        validate_mask(&e.mask, rows)?;
        w.write(&e.count.to_le_bytes())?;
        for n in [e.first.atom, e.first.qualifier, e.first.cutoff] {
            w.write(&n.to_le_bytes())?;
        }
        for v in e.mask.bits.iter().chain(&e.mask.valid) {
            w.write(&v.to_le_bytes())?;
        }
    }
    w.finish()
}
pub fn load(path: &std::path::Path, context: &str, budget: usize) -> Result<Vec<Entry>> {
    let b = crate::dense_io::read(path, budget)?;
    let mut r = crate::dense_io::Reader::new(&b);
    if r.bytes(8)? != b"FDBANK01" || r.bytes(64)? != context.as_bytes() {
        return Err("dense bank context/version".into());
    }
    let rows = usize::try_from(r.u64()?).map_err(|_| "bank rows overflow")?;
    let count = usize::try_from(r.u64()?).map_err(|_| "bank states overflow")?;
    if rows == 0 || count == 0 {
        return Err("empty bank".into());
    }
    let words = rows.checked_add(63).ok_or("rows overflow")? / 64;
    let width = words
        .checked_mul(16)
        .and_then(|v| v.checked_add(40))
        .ok_or("record overflow")?;
    if count.checked_mul(width).and_then(|v| v.checked_add(88)) != Some(b.len())
        || count.checked_mul(width + 320).map_or(true, |v| v > budget)
    {
        return Err("bank count/budget mismatch".into());
    }
    let mut out = Vec::with_capacity(count);
    for _ in 0..count {
        let n = r.u128()?;
        let first = Coordinate {
            atom: r.u64()?,
            qualifier: r.u64()?,
            cutoff: r.u64()?,
        };
        let mut m = Mask::empty(rows);
        for v in m.bits.iter_mut().chain(&mut m.valid) {
            *v = r.u64()?;
        }
        validate_mask(&m, rows)?;
        if n == 0 {
            return Err("zero bank multiplicity".into());
        }
        out.push(Entry {
            mask: m,
            count: n,
            first,
        });
    }
    r.end()?;
    Ok(out)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn collision_checked_identity_preserves_counts_and_coordinates() {
        let mut a = Mask::empty(67);
        for t in 0..67 {
            a.set(t, t % 2 == 0, true);
        }
        let mut b = a.clone();
        b.set(2, false, true);
        let mut bank = Builder::new(67, 4096).unwrap();
        assert_eq!(
            bank.intern_key(
                &a,
                7,
                Coordinate {
                    atom: 5,
                    ..Coordinate::default()
                },
                1
            )
            .unwrap(),
            0
        );
        assert_eq!(
            bank.intern_key(&b, 11, Coordinate::default(), 1).unwrap(),
            1
        );
        assert_eq!(
            bank.intern_key(&a, 13, Coordinate::default(), 1).unwrap(),
            0
        );
        assert_eq!(bank.entries.len(), 2);
        assert_eq!(bank.entries[0].count, 20);
        assert_eq!(bank.addresses, 31);
        assert_eq!(bank.entries[0].first, Coordinate::default());
        b.bits[1] |= 1 << 20;
        assert!(bank.intern(&b, 1, Coordinate::default()).is_err());
    }
}
