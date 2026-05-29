import os
import tempfile
import uuid
import shutil
from pathlib import Path

import torch
import torchaudio
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from loguru import logger
import uvicorn

# MMAudio imports
from mmaudio.eval_utils import (ModelConfig, all_model_cfg, generate, load_video)
from mmaudio.model.flow_matching import FlowMatching
from mmaudio.model.networks import get_my_mmaudio
from mmaudio.model.utils.features_utils import FeaturesUtils

app = FastAPI(title="MMAudio V2A API")

net = None
fm = None
feature_utils = None
seq_cfg = None

@app.on_event("startup")
def startup_event():
    global net, fm, feature_utils, seq_cfg
    logger.info("Initializing MMAudio model...")
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    
    variant = os.environ.get("MMAUDIO_VARIANT", "large_44k_v2")
    
    try:
        if variant not in all_model_cfg:
            raise ValueError(f"Unknown model variant: {variant}")
            
        model_cfg: ModelConfig = all_model_cfg[variant]
        model_cfg.download_if_needed()
        seq_cfg = model_cfg.seq_cfg
        
        dtype = torch.bfloat16
        
        # Load pre-trained model
        net = get_my_mmaudio(model_cfg.model_name).to(device, dtype).eval()
        net.load_weights(torch.load(model_cfg.model_path, map_location=device, weights_only=True))
        
        feature_utils = FeaturesUtils(tod_vae_ckpt=model_cfg.vae_path,
                                      synchformer_ckpt=model_cfg.synchformer_ckpt,
                                      enable_conditions=True,
                                      mode=model_cfg.mode,
                                      bigvgan_vocoder_ckpt=model_cfg.bigvgan_16k_path,
                                      need_vae_encoder=False)
        feature_utils = feature_utils.to(device, dtype).eval()
        
        fm = FlowMatching(min_sigma=0, inference_mode='euler', num_steps=25)
        
        logger.info("MMAudio model loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load MMAudio model: {e}")

@app.post("/generate_v2a")
async def generate_v2a_endpoint(
    video: UploadFile = File(...),
    prompt: str = Form(""),
    guidance_scale: float = Form(4.5),
    num_inference_steps: int = Form(25)
):
    if net is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Model is not loaded.")
        
    try:
        tmp_dir = tempfile.mkdtemp()
        video_path = Path(tmp_dir) / f"input_{uuid.uuid4().hex}.mp4"
        with open(video_path, "wb") as f:
            shutil.copyfileobj(video.file, f)
            
        logger.info(f"Processing V2A request for video: {video.filename}, prompt: {prompt}")
        
        # MMAudio Inference
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        duration = 8.0 # fallback duration
        
        video_info = load_video(video_path, duration)
        clip_frames = video_info.clip_frames.unsqueeze(0)
        sync_frames = video_info.sync_frames.unsqueeze(0)
        duration = video_info.duration_sec
        
        seq_cfg.duration = duration
        net.update_seq_lengths(seq_cfg.latent_seq_len, seq_cfg.clip_seq_len, seq_cfg.sync_seq_len)
        
        rng = torch.Generator(device=device)
        rng.manual_seed(42)
        
        fm_instance = FlowMatching(min_sigma=0, inference_mode='euler', num_steps=num_inference_steps)
        
        audios = generate(clip_frames,
                          sync_frames, [prompt],
                          negative_text=[""],
                          feature_utils=feature_utils,
                          net=net,
                          fm=fm_instance,
                          rng=rng,
                          cfg_strength=guidance_scale)
                          
        audio_tensor = audios.float().cpu()[0]
        
        out_wav = Path(tmp_dir) / f"output_{uuid.uuid4().hex}.wav"
        torchaudio.save(str(out_wav), audio_tensor, seq_cfg.sampling_rate)
        
        return FileResponse(
            out_wav, 
            media_type="audio/wav", 
            filename="generated.wav",
            background=None
        )
        
    except Exception as e:
        logger.exception("Error during generation")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
