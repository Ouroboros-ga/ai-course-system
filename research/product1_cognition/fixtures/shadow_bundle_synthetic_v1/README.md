# Synthetic read-only Shadow bundle

This directory is fully synthetic. IDs `1` and `2` are fixture identifiers,
not students or courses. It demonstrates the exact five-file bundle contract
accepted by `tools/run_shadow_bundle.py`; it is not evidence that a real Shadow
has been approved.

```powershell
$env:PYTHONPATH = 'research/product1_cognition'
backend/.venv/Scripts/python.exe research/product1_cognition/tools/run_shadow_bundle.py --bundle-dir research/product1_cognition/fixtures/shadow_bundle_synthetic_v1
```
