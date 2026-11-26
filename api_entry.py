import argparse

from rooms.http import LiveCaptionHandler, create_runtime, make_server


class CaptionApiHandler(LiveCaptionHandler):
    def _get(self):
        if self.path == '/healthz':
            return 200, {'status': 'ready'}
        return super()._get()


def main():
    parser = argparse.ArgumentParser(description='Start the live caption API')
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--host', choices=('127.0.0.1',), default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    runtime = create_runtime(args.data_dir)
    with make_server(runtime, args.host, args.port, CaptionApiHandler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
