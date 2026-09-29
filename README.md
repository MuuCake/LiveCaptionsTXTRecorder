# LiveCaptionsTXTRecorder

A lightweight Windows 11 tool that saves Windows Live Captions directly to TXT files.

## Features

- Automatically opens Windows Live Captions
- Saves captions to TXT
- Pause / Continue
- Stop & Save
- Automatically saves if Live Captions is closed
- Supports Windows light and dark mode
- High-DPI display support
- No Python installation required for the packaged EXE

## Requirements

- Windows 11
- Windows Live Captions

Tested on Windows 11 x64. Other system configurations may vary.

## Download

Download the latest version from **Releases**:

`LiveCaptionsTXTRecorder.exe`

## How to Use

1. Open `LiveCaptionsTXTRecorder.exe`
2. Choose a TXT save location
3. Click **Start Recording**
4. Use **Pause / Continue** when needed
5. Click **Stop & Save** to finish

If Windows Live Captions is closed while recording, the current TXT file is saved automatically.

## Notes

- Speech recognition is provided by Windows Live Captions
- The app includes duplicate-reduction logic
- TXT files support Korean, Chinese, Japanese, English, and other languages supported by Windows Live Captions

## Source Code

Main source file:

`LiveCaptions.py`

## License

MIT License
