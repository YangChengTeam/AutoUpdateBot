import os
import paramiko

class SftpUploader:
    def __init__(self, sftp_config):
        """
        :param sftp_config: dict {'host': '...', 'user': '...', ...}
        """
        self.set_config(sftp_config)

    def set_config(self, sftp_config):
        self.cfg = sftp_config

    def upload(self, remote_dir, local_path):
        print(f"--> [上传] 准备传输到 {self.cfg['host']}...")
        
        transport = None
        sftp = None
        try:
            # 建立连接
            transport = paramiko.Transport((self.cfg['host'], self.cfg['port']))
            transport.connect(username=self.cfg['user'], password=self.cfg['password'])
            sftp = paramiko.SFTPClient.from_transport(transport)
           
            # 处理远程路径
            filename = os.path.basename(local_path)
            remote_path = os.path.join(remote_dir, filename).replace("\\", "/") # Linux 路径符
            print(f"--> [上传] 正在传输到 {remote_path}...")
            # 上传 (可以加 callback 监控进度)
            sftp.put(local_path, remote_path)
            print(f"    [完成] 文件已上传: {remote_path}")
            return True

        except Exception as e:
            print(f"    [失败] SFTP 错误: {e}")
            return False
            
        finally:
            if sftp: sftp.close()
            if transport: transport.close()

    def upload_apk(self, localpath):
        return self.upload(self.cfg["remote_dir"], localpath)

    def upload_screenhot(self, localpath):
        return self.upload(self.cfg["remote_screenshots_dir"], localpath)