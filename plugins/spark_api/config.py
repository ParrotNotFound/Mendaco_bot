from pydantic import BaseModel, Field

class Config(BaseModel):
    """插件配置类，对应 .env 文件中的配置项"""
    # 讯飞星火 API 配置
    spark_app_id: str = Field("", description="讯飞星火 AppID")
    spark_api_key: str = Field("", description="讯飞星火 API Key")
    spark_api_secret: str = Field("", description="讯飞星火 API Secret")
    spark_api_host: str = Field("ws://spark-api.xf-yun.com/v1.1/chat", description="星火 API 主机地址")
    
    # 上下文管理配置（可选，可从代码默认值覆盖）
    spark_max_turns: int = Field(10, description="最大对话轮次")
    spark_timeout_minutes: int = Field(30, description="上下文超时时间（分钟）")