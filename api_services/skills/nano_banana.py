import os
import uuid
from django.conf import settings
from google import genai
from google.genai import types
from .decorators import register_skill

@register_skill
def generate_image_with_gemini_nano_banana(prompt: str, reference_image_path: str = None) -> str:
    """
    使用 Gemini Nano Banana (Imagen 4) 生成图片。
    
    :param prompt: 图片生成的提示词描述
    :param reference_image_path: (可选) 参考图片的本地文件路径，用于作为生图的参考
    :return: generated_image_path or error_message
    """
    try:
        try:
            from api_services.models import APIKey
            gem_api_key = APIKey.objects.get(name='Gemini Auto Process').key
        except:
            gem_api_key = str(settings.GEMINI_API_KEY).strip()
        client = genai.Client(api_key=gem_api_key)
        
        # 检查是否提供了参考图片且文件存在
        if reference_image_path and os.path.exists(reference_image_path):
            print(f"使用参考图片: {reference_image_path}")
            try:
                # 读取图片
                with open(reference_image_path, "rb") as f:
                    image_bytes = f.read()
                
                # 构造 RawReferenceImage
                raw_ref_image = types.RawReferenceImage(
                    reference_id=1,
                    reference_image=types.Image(image_bytes=image_bytes),
                )
                
                # 使用 edit_image 接口
                response = client.models.edit_image(
                    model='imagen-3.0-capability-001', 
                    prompt=prompt,
                    reference_images=[raw_ref_image],
                    config=types.EditImageConfig(
                        number_of_images=1,
                    )
                )
            except Exception as e_edit:
                print(f"Edit Image failed, trying fallback: {e_edit}")
                # 降级处理: 使用 Imagen 4 生成
                response = client.models.generate_images(
                    model='imagen-4.0-generate-001',
                    prompt=f"{prompt} (Note: Reference image context missing)", 
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                    )
                )
        else:
            # 普通文生图
            response = client.models.generate_images(
                model='imagen-4.0-generate-001',
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                )
            )
            
        if response.generated_images:
            image = response.generated_images[0].image
            
            # 保存图片到 media 目录
            media_root = settings.MEDIA_ROOT
            save_dir = os.path.join(media_root, 'generated_images')
            os.makedirs(save_dir, exist_ok=True)
            
            filename = f"gen_{uuid.uuid4().hex}.png"
            file_path = os.path.join(save_dir, filename)
            
            image.save(file_path)
            
            # 返回相对路径或绝对路径，视需求而定，这里返回绝对路径方便后续处理
            return f"图片已生成并保存至: {file_path}"
            
        return "图片生成失败: 未返回图片数据"
    except Exception as e:
        error_msg = f"Gemini Nano Banana (Imagen 4) 生成图片失败: {str(e)}"
        print(error_msg)
        return error_msg
    