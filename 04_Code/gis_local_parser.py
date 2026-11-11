"""Optional DeepSeek parsing for a local geographic dataset; no geometry sent."""
import os
from pathlib import Path
from gis_natural import parse_task


def make_client():
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    key = os.getenv('DEEPSEEK_API_KEY')
    if not key:
        raise ValueError('DeepSeek尚未配置：请在项目.env中设置DEEPSEEK_API_KEY，或选择本地规则。')
    return OpenAI(api_key=key,base_url='https://api.deepseek.com',timeout=30,max_retries=0)


def parse_local_query(query,names,mode):
    if mode == '本地规则（无需API）':
        return parse_task(query,names)
    if mode != 'DeepSeek（API指令解析）':
        raise ValueError('不支持的指令解析方式。')
    # Supply only explicitly mentioned names, not thousands of unrelated roads.
    # parse_task still checks supported intent, distance, fields and mentions.
    candidates=[name for name in names if name and not name.isdigit() and name in query]
    if not candidates:
        raise ValueError('请在指令中写出当前数据包中的完整道路名称，也可先在下方搜索道路。')
    client=make_client()
    try:
        return parse_task(query,candidates,client)
    except ValueError:
        raise
    except Exception as exc:
        from openai import APIStatusError,APIConnectionError,APITimeoutError
        if isinstance(exc,APITimeoutError):
            raise ValueError('DeepSeek请求超时（30秒），请重试或改用本地规则。') from exc
        if isinstance(exc,APIStatusError):
            if exc.status_code == 402:
                raise ValueError('DeepSeek API余额不足，请检查额度或改用本地规则。') from exc
            raise ValueError(f'DeepSeek请求失败（HTTP {exc.status_code}），请检查配置或稍后重试。') from exc
        if isinstance(exc,APIConnectionError):
            raise ValueError('DeepSeek连接失败，请检查网络或改用本地规则。') from exc
        raise ValueError('DeepSeek指令解析未完成，请重试或改用本地规则。') from exc
