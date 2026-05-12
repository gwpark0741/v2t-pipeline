import time
from google import genai
from google.genai import types


def get_client(api_key: str) -> genai.Client:
    """Gemini 클라이언트 생성"""
    return genai.Client(api_key=api_key)


def upload_video(client: genai.Client, video_path: str, max_timeout: int = 200) -> tuple[str, str]:
    """영상 파일을 Gemini File API에 업로드 -> file_uri와 file_name 반환"""
    video_file = client.files.upload(file=video_path)
    start_time = time.time()

    print(f"Uploading {video_file.name} to Gemini File API...")

    while video_file.state.name == "PROCESSING":
        # 타임아웃 체크
        if time.time() - start_time > max_timeout:
            raise TimeoutError("File upload timed out.")

        print(f"File {video_file.name} is still processing...")
        time.sleep(10)  # 10초마다 상태 확인
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise RuntimeError(f"File upload failed: {video_file.failure_reason}")

    print(f"File {video_file.name} upload completed successfully.")
    return video_file.uri, video_file.name


def generate_response(
    client: genai.Client,
    user_prompt: str,
    file_name: str,
    model_name: str,
    temperature: float,
    seed: int,
    system_prompt: str = "",
) -> str:
    """Gemini 모델에 영상 파일과 프롬프트 전달하여 응답 생성"""
    video_ref = client.files.get(name=file_name)

    response = client.models.generate_content(
        model=model_name,
        contents=[video_ref, user_prompt],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            seed=seed,
            response_mime_type="application/json",
        )
    ) 
    return response.text