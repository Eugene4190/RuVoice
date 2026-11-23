# Third-party notices for the optional offline RUAccent module

The original RuVoice project license remains in the repository root. This file
covers only the separately added optional text-correction module and its
upstream components.

## RUAccent

The neural text-processing pipeline and model artifacts are based on RUAccent
by Denis Petrov (Den4ikAI). The upstream GitHub repository and the Hugging Face
`ruaccent/accentuator` model card currently identify the v1 system as MIT.
The corresponding license text is in `RUACCENT-MIT.txt`.

- Source: https://github.com/Den4ikAI/ruaccent
- Model card: https://huggingface.co/ruaccent/accentuator

## stressonnx reference implementation

The Kotlin implementation follows the four-stage ONNX pipeline and tokenizer
alignment described by TigreGotico's `stressonnx` RUAccent backend. The source
reference is Apache License 2.0; the license text is in
`STRESSONNX-APACHE-2.0.txt`.

- Source: https://github.com/TigreGotico/stressonnx
- RUAccent backend: https://github.com/TigreGotico/stressonnx/blob/dev/stressonnx/backends/ruaccent.py

## ONNX Runtime Android

The application uses the Maven artifact
`com.microsoft.onnxruntime:onnxruntime-android`. Refer to Microsoft's license
and notices distributed with that dependency:
https://github.com/microsoft/onnxruntime

## Hugging Face Tokenizers (Rust)

The native tokenizer bridge uses the Rust `tokenizers` crate and `jni` crate as
Cargo dependencies. Their respective source licenses and notices are retained
by the package managers when those dependencies are fetched. The bridge source
added in this repository is in `native/`.
