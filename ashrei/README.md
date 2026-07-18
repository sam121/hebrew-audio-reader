# Ashrei Line Practice

A static GitHub Pages practice page for learning Ashrei line by line.

The `audio/` clips were cut from the supplied learner-speed MP3 into 24 line-level `.m4a` files. The page uses Hebrew text with an original egalitarian English rendering beneath each line.

## Updating Clip Times

Edit `timings.csv`, then regenerate the clips:

```sh
python3 ashrei/scripts/build_clips.py
```

Times can be entered as seconds (`31.45`) or timecodes (`0:31.45`). The source MP3 defaults to:

```text
/Users/samueltaylor/Downloads/Ashrei - Learner's Speed [Qy-gdPGuUmo].mp3
```
