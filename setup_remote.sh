#!/bin/bash
set -e
echo "Starting setup..."

# 1. Update and install basic tools
apt-get update && apt-get install -y git-lfs curl tmux

# 2. Clone repo if not exists
if [ ! -d "HunyuanVideo-Foley" ]; then
    git clone https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley.git
fi
cd HunyuanVideo-Foley

# 3. Install requirements
pip install -r requirements.txt
pip install fastapi uvicorn python-multipart

# 4. Download weights
echo "Downloading HunyuanVideo-Foley weights..."
# We will use huggingface-cli to download to a specific directory
huggingface-cli download tencent/HunyuanVideo-Foley --local-dir weights

# 5. Move api server script
cp ../hunyuan_api_server.py .

echo "Setup complete! To run the server:"
echo "export HUNYUAN_MODEL_PATH=$(pwd)/weights"
echo "python hunyuan_api_server.py"
