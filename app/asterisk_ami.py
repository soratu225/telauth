"""
app/asterisk_ami.py - Asterisk Manager Interface (AMI) クライアント
"""
import asyncio
import logging
from panoramisk import Manager
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class AsteriskError(Exception):
    """Asterisk APIエラー"""
    pass

class AsteriskAMIClient:
    """Asterisk AMIを通して通話のOriginate(発信)を行うクライアント"""
    
    def __init__(self):
        self.host = settings.asterisk_host
        self.port = settings.asterisk_ami_port
        self.username = settings.asterisk_ami_username
        self.secret = settings.asterisk_ami_password
        self.caller_id = settings.brastel_sip_caller_id
        
    async def initiate_call(self, phone_number: str, wav_filename: str) -> dict:
        """
        指定した電話番号へ発信し、応答後に指定のWAVファイルを再生する。

        Args:
            phone_number: 発信先の電話番号
            wav_filename: Asteriskが再生するWAVファイル名(拡張子不要)
        """
        # Managerを毎回インスタンス化して接続（コネクションプールを作ることも可能）
        manager = Manager(
            host=self.host,
            port=self.port,
            username=self.username,
            secret=self.secret,
        )
        
        try:
            await manager.connect()
            logger.info(f"Asterisk AMI 接続成功: {self.host}:{self.port}")
            
            # 発信アクションの組み立て
            action = {
                'Action': 'Originate',
                'Channel': f'PJSIP/{phone_number}@{settings.asterisk_endpoint}',
                'Context': settings.asterisk_context,
                'Exten': phone_number,
                'Priority': 1,
                'CallerID': self.caller_id,
                'Variable': f'WAVFILE={wav_filename}',  # ダイヤルプランにWAVパスを渡す
                'Timeout': settings.asterisk_call_timeout_ms,
                'Async': 'true',
            }
            
            logger.info(f"Originate 発信要求: {phone_number} (WAV: {wav_filename})")
            response = await manager.send_action(action)
            
            if response.success:
                logger.info(f"Originate 成功: {response.message}")
                return {"status": "initiated", "call_id": response.headers.get("ActionID", "unknown")}
            else:
                logger.error(f"Originate 失敗: {response.message}")
                raise AsteriskError(f"発信失敗: {response.message}")
                
        except Exception as e:
            logger.error(f"Asterisk AMI エラー: {e}")
            raise AsteriskError(f"Asteriskへの接続・発信中にエラー: {e}")
        finally:
            manager.close()

_client: AsteriskAMIClient | None = None

def get_asterisk_client() -> AsteriskAMIClient:
    """シングルトンのAsteriskAMIClientインスタンスを返す"""
    global _client
    if _client is None:
        _client = AsteriskAMIClient()
    return _client
