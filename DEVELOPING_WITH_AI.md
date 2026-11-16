# How to develop with mistral vibe on MacOs

Similar setup apply for Linux.

What to install (i.e. with brew)
- uv 0.13.7
- rtk 1.2.0
- openspec 1.16.1 (use npm `install -g @fission-ai/openspec@1.16.1`)
- 


Execute

```sh
uv venv -p 3.14
uv pip compile --refresh requirements.in backend/requirements.txt > requirements.txt
uv pip install -r requirements.txt
# Activate env and then
make help
```

Use the script sh/refreshDeps.sh if you need to upgrade deps.


