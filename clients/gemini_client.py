import time
import google.generativeai as genai


def upload_video(video_path: str) -> str:
    """영상 파일을 Gemini File API에 업로드하고 URI 반환"""
    video_file = genai.upload_file(video_path)

    while video_file.state.name == "PROCESSING":
        time.sleep(2)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name == "FAILED":
        raise RuntimeError(f"File upload failed: {video_file.failure_reason}")

    return video_file.uri


def generate_response(prompt: str, video_uri: str, model_name: str, temperature: float, seed: int) -> str:
    """Gemini 모델에 프롬프트와 영상 URI 전달하여 응답 생성"""
    model = genai.GenerativeModel(model_name)
    file_ref = genai.get_file(video_uri.split("/")[-1])

    response = model.generate_content(
        [file_ref, prompt],
        generation_config=genai.GenerationConfig(
            temperature=temperature,
            seed=seed,
            response_mime_type="application/json",
        )
    )
    return response.text