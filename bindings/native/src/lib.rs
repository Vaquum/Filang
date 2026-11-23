use filang::engine_session::{Session, ABI_VERSION, MAX_PAYLOAD};
use std::{ptr, slice};

#[derive(Default)]
pub struct Handle {
    session: Session,
    output: Vec<u8>,
}

#[no_mangle]
pub extern "C" fn filang_abi_version() -> u32 {
    ABI_VERSION
}

#[no_mangle]
pub extern "C" fn filang_session_new() -> *mut Handle {
    Box::into_raw(Box::new(Handle::default()))
}

/// # Safety
/// The pointer is null or a live handle obtained from filang_session_new.
/// A live handle may be dropped exactly once, with no outstanding calls.
#[no_mangle]
pub unsafe extern "C" fn filang_session_drop(handle: *mut Handle) {
    if !handle.is_null() {
        drop(Box::from_raw(handle));
    }
}

/// Used by WebAssembly clients to copy a request into linear memory.
#[no_mangle]
pub extern "C" fn filang_alloc(len: usize) -> *mut u8 {
    if len == 0 || len > MAX_PAYLOAD {
        return ptr::null_mut();
    }
    Box::into_raw(vec![0u8; len].into_boxed_slice()) as *mut u8
}

/// # Safety
/// The pointer is null or was allocated by filang_alloc with the same length
/// and has not already been freed. No caller may access the buffer afterward.
#[no_mangle]
pub unsafe extern "C" fn filang_free(data: *mut u8, len: usize) {
    if !data.is_null() {
        drop(Box::from_raw(ptr::slice_from_raw_parts_mut(data, len)));
    }
}

/// # Safety
/// The handle is live and exclusive to this call. The input is readable for
/// len bytes, lives through the call and does not overlap the handle or output.
#[no_mangle]
pub unsafe extern "C" fn filang_call(handle: *mut Handle, data: *const u8, len: usize) -> u32 {
    let handle = match handle.as_mut() {
        Some(handle) => handle,
        None => return 1,
    };
    if len == 0 || len > MAX_PAYLOAD || data.is_null() {
        handle.output = b"invalid Filang engine request buffer".to_vec();
        return 1;
    }
    let request = slice::from_raw_parts(data, len);
    let reply = if let Some(payload) = request.strip_prefix(b"composer-positions-packed\n") {
        handle.session.composer_positions_packed(payload)
    } else {
        handle.session.call(request).map(String::into_bytes)
    };
    match reply {
        Ok(value) => {
            handle.output = value;
            0
        }
        Err(error) => {
            handle.output = error.into_bytes();
            1
        }
    }
}

/// # Safety
/// The handle is live. The pointer is valid until the next call or drop.
#[no_mangle]
pub unsafe extern "C" fn filang_output(handle: *const Handle) -> *const u8 {
    let handle = &*handle;
    handle.output.as_ptr()
}

/// # Safety
/// The handle is live.
#[no_mangle]
pub unsafe extern "C" fn filang_output_len(handle: *const Handle) -> usize {
    let handle = &*handle;
    handle.output.len()
}
