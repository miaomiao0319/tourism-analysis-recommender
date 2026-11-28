"""Launch locally with python -m scripts.web [--demo]."""
import argparse
from backend.app import create_app


def create_demo_app():
    from scripts.web_sample import BATCH, SampleRepository
    return create_app({"ACTIVE_BATCH_ID": BATCH}, SampleRepository())


def main():
    parser = argparse.ArgumentParser(description="启动山河图鉴网站")
    parser.add_argument("--demo", action="store_true", help="仅使用标记为 test 的页面联调样本")
    parser.add_argument("--open-browser", action="store_true", help="启动本地演示并打开浏览器")
    args = parser.parse_args()
    app = create_demo_app() if args.demo else create_app()
    if args.open_browser:
        from threading import Thread
        from webbrowser import open as open_browser
        from werkzeug.serving import make_server

        dataset = app.test_client().get("/api/v1/dataset")
        if dataset.status_code != 200:
            error = dataset.get_json()["error"]
            parser.exit(1, f"{error['code']}: {error['message']}\n")
        with make_server("127.0.0.1", int(app.config["FLASK_PORT"]), app) as server:
            url = f"http://127.0.0.1:{server.server_port}/"
            print(f"Shanhe Atlas: {url} (Ctrl+C to stop)", flush=True)
            Thread(target=open_browser, args=(url,), daemon=True).start()
            server.serve_forever()
        return
    app.run(host=app.config["FLASK_HOST"], port=int(app.config["FLASK_PORT"]), debug=False)


if __name__ == "__main__":
    main()
