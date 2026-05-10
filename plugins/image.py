import base64
from io import BytesIO

from PIL import ImageFont, ImageDraw, Image


path = './src/static/high_eq_image.png'
fontpath = "./src/static/msyh.ttc"


def draw_text(img_pil, text, offset_x):
    draw = ImageDraw.Draw(img_pil)
    font = ImageFont.truetype(fontpath, 48)
    width, height = draw.textsize(text, font)
    x = 5
    if width > 390:
        font = ImageFont.truetype(fontpath, int(390 * 48 / width))
        width, height = draw.textsize(text, font)
    else:
        x = int((400 - width) / 2)
    draw.rectangle((x + offset_x - 2, 360, x + 2 + width + offset_x, 360 + height * 1.2), fill=(0, 0, 0, 255))
    draw.text((x + offset_x, 360), text, font=font, fill=(255, 255, 255, 255))


def text_to_image(text):
    font = ImageFont.truetype(fontpath, 24)
    padding = 10
    margin = 4
    text_list = text.split('\n')
    
    # 获取字体度量指标
    ascent, descent = font.getmetrics()
    h_total = ascent + descent  # 总行高
    
    # 计算最大宽度
    max_width = 0
    for text in text_list:
        text_width = font.getlength(text)  # 获取文本宽度
        max_width = max(max_width, text_width)
    
    # 计算画布尺寸
    wa = int(max_width + padding * 2)
    ha = int(h_total * len(text_list) + margin * (len(text_list) - 1) + padding * 2)
    
    # 创建图像
    i = Image.new('RGB', (wa, ha), color=(255, 255, 255))
    draw = ImageDraw.Draw(i)
    
    # 绘制文本
    for j, text in enumerate(text_list):
        # 设置颜色
        clr = [0, 0, 0]
        # 计算Y坐标（考虑基线位置）
        y = padding + ascent + j * (h_total + margin)
        draw.text((padding, y), text, font=font, fill=tuple(clr))
    
    return i

#from PIL import Image, ImageDraw, ImageFont

def text_to_image2(text):
    font = ImageFont.truetype(fontpath, 24)
    padding = 10
    margin = 4
    text_list = text.split('\n')
    
    # 获取字体度量指标
    ascent, descent = font.getmetrics()
    h_total = ascent + descent  # 总行高
    
    # 计算最大宽度
    max_width = 0
    for text in text_list:
        text_width = font.getlength(text)  # 获取文本宽度
        max_width = max(max_width, text_width)
    
    # 计算画布尺寸
    wa = int(max_width + padding * 2)
    ha = int(h_total * len(text_list) + margin * (len(text_list) - 1) + padding * 2)
    
    # 创建图像
    i = Image.new('RGB', (wa, ha), color=(255, 255, 255))
    draw = ImageDraw.Draw(i)
    
    # 绘制文本
    for j, text in enumerate(text_list):
        # 设置颜色
        clr = [0, 0, 0]
        if '[S]' in text:
            clr = [255, 165, 0]
        elif '[SS]' in text:
            clr = [255, 114, 0]
        elif '[SSS]' in text:
            clr = [255, 45, 0]
        elif '[LEGEND]' in text:
            clr = [255, 0, 255]
        
        # 计算Y坐标（考虑基线位置）
        y = padding + ascent + j * (h_total + margin)
        draw.text((padding, y), text, font=font, fill=tuple(clr))
    
    return i



def text_to_image3(text):
    font = ImageFont.truetype(fontpath, 24)
    padding = 10
    margin = 4
    text_list = text.split('\n')
    max_width = 0
    for text in text_list:
        w, h = font.getsize(text)
        max_width = max(max_width, w)
    wa = max_width + padding * 2
    ha = h * len(text_list) + margin * (len(text_list) - 1) + padding * 2
    i = Image.new('RGB', (wa, ha), color=(255, 255, 255))
    draw = ImageDraw.Draw(i)
    for j in range(len(text_list)):
        text = text_list[j]
        clr = [0,0,0]
        if text.find('[SSS]')>=0:
            clr = [255,45,0]
        elif text.find('[FC]')>=0:
            clr = [0,180,0]
        elif text.find('[FDX]')>=0:
            clr = [255,45,0]
        elif text.find('[AP]')>=0:
            clr = [255,114,0]
        draw.text((padding, padding + j * (margin + h)), text, font=font, fill=(clr[0],clr[1],clr[2]))
    return i

def image_to_base64(img, format='PNG'):
    output_buffer = BytesIO()
    img.save(output_buffer, format)
    byte_data = output_buffer.getvalue()
    base64_str = base64.b64encode(byte_data)
    return base64_str
