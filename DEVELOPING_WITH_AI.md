# How to develop with mistral vibe on MacOs

Install uv with brew
Execute

```sh
uv venv -p 3.14
uv pip compile --refresh requirements.in > requirements.txt
uv pip install -r requirements.txt
# Activate env and then
make help
```

Same setup apply on Linux