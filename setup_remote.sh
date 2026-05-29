#!/bin/bash
set -e
echo "Starting setup..."

# 1. Update and install basic tools
apt-get update && apt-get install -y git-lfs curl tmux

# 2. Install ffmpeg<7 for torchaudio compatibility
conda install -y -c conda-forge 'ffmpeg<7' || apt-get install -y ffmpeg

# 3. Clone repo if not exists
if [ ! -d "MMAudio" ]; then
    git clone https://github.com/hkchengrex/MMAudio.git
fi
cd MMAudio

# 4. Install requirements
pip install -e .
pip install fastapi uvicorn python-multipart loguru torchaudio torchvision

# 5. Move api server script
cp ../mmaudio_api_server.py .

echo "Setup complete! To run the server:"
echo "python mmaudio_api_server.py"

