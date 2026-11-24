"""Launch locally with python -m scripts.web [--demo]."""
import argparse
from backend.app import create_app


def main():
    parser = argparse.ArgumentParser(description="启动山河图鉴网站")
    parser.add_argument("--demo", action="store_true", help="仅使用标记为 test 的页面联调样本")
    args = parser.parse_args()
    if args.demo:
        from scripts.web_sample import BATCH, SampleRepository
        app = create_app({"ACTIVE_BATCH_ID": BATCH}, SampleRepository())
    else:
        app = create_app()
    app.run(host=app.config["FLASK_HOST"], port=int(app.config["FLASK_PORT"]), debug=False)


if __name__ == "__main__":
    main()
