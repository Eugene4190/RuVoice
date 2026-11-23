// JNI tokenizer bridge for the RUAccent Android port. See licenses/THIRD_PARTY_NOTICES.md.
use jni::objects::{JByteArray, JClass, JString};
use jni::sys::{jint, jintArray, jlong};
use jni::JNIEnv;
use tokenizers::tokenizer::Tokenizer;

const COLS: usize = 6;

fn to_utf16_offset(text: &str, char_offset: usize) -> i32 {
    text.chars().take(char_offset).map(char::len_utf16).sum::<usize>() as i32
}

fn encode_flat(tokenizer: &Tokenizer, first: &str, second: Option<&str>) -> Result<Vec<i32>, String> {
    let mut encoded = match second {
        Some(pair) => tokenizer.encode_char_offsets((first, pair), true),
        None => tokenizer.encode_char_offsets(first, true),
    }.map_err(|e| e.to_string())?;

    let ids = encoded.get_ids();
    let type_ids = encoded.get_type_ids();
    let attention = encoded.get_attention_mask();
    let offsets = encoded.get_offsets();
    let special = encoded.get_special_tokens_mask();

    let mut result = Vec::with_capacity(ids.len() * COLS);
    for index in 0..ids.len() {
        let (start, end) = offsets[index];
        // Offsets for the second sequence in pair-encoding are relative to the second string.
        // Pair encodings are used only by the NLI classifier, which does not consume offsets.
        let (start16, end16) = if second.is_some() {
            (0, 0)
        } else {
            (to_utf16_offset(first, start), to_utf16_offset(first, end))
        };
        result.push(ids[index] as i32);
        result.push(type_ids.get(index).copied().unwrap_or(0) as i32);
        result.push(attention.get(index).copied().unwrap_or(1) as i32);
        result.push(start16);
        result.push(end16);
        result.push(special.get(index).copied().unwrap_or(0) as i32);
    }
    Ok(result)
}

fn int_array(mut env: JNIEnv, values: &[i32]) -> jintArray {
    let array = match env.new_int_array(values.len() as jint) {
        Ok(value) => value,
        Err(_) => return std::ptr::null_mut(),
    };
    if env.set_int_array_region(&array, 0, values).is_err() {
        return std::ptr::null_mut();
    }
    array.into_raw()
}

#[no_mangle]
pub extern "system" fn Java_ru_kost_ruvoice_text_HfTokenizer_nativeCreate(
    mut env: JNIEnv,
    _class: JClass,
    tokenizer_json: JByteArray,
) -> jlong {
    let bytes = match env.convert_byte_array(tokenizer_json) {
        Ok(value) => value,
        Err(_) => return 0,
    };
    let mut tokenizer = match Tokenizer::from_bytes(&bytes) {
        Ok(value) => value,
        Err(_) => return 0,
    };
    if tokenizer.with_truncation(None).is_err() {
        return 0;
    }
    Box::into_raw(Box::new(tokenizer)) as jlong
}

#[no_mangle]
pub extern "system" fn Java_ru_kost_ruvoice_text_HfTokenizer_nativeEncode(
    mut env: JNIEnv,
    _class: JClass,
    handle: jlong,
    text: JString,
) -> jintArray {
    if handle == 0 { return std::ptr::null_mut(); }
    let value: String = match env.get_string(&text) {
        Ok(v) => v.into(),
        Err(_) => return std::ptr::null_mut(),
    };
    let tokenizer = unsafe { &*(handle as *const Tokenizer) };
    match encode_flat(tokenizer, &value, None) {
        Ok(values) => int_array(env, &values),
        Err(_) => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "system" fn Java_ru_kost_ruvoice_text_HfTokenizer_nativeEncodePair(
    mut env: JNIEnv,
    _class: JClass,
    handle: jlong,
    first: JString,
    second: JString,
) -> jintArray {
    if handle == 0 { return std::ptr::null_mut(); }
    let first_value: String = match env.get_string(&first) {
        Ok(v) => v.into(),
        Err(_) => return std::ptr::null_mut(),
    };
    let second_value: String = match env.get_string(&second) {
        Ok(v) => v.into(),
        Err(_) => return std::ptr::null_mut(),
    };
    let tokenizer = unsafe { &*(handle as *const Tokenizer) };
    match encode_flat(tokenizer, &first_value, Some(&second_value)) {
        Ok(values) => int_array(env, &values),
        Err(_) => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "system" fn Java_ru_kost_ruvoice_text_HfTokenizer_nativeDispose(
    _env: JNIEnv,
    _class: JClass,
    handle: jlong,
) {
    if handle != 0 {
        unsafe { drop(Box::from_raw(handle as *mut Tokenizer)); }
    }
}
