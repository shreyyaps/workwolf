from fastapi import FastAPI, Request


def register_middlewares(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-App-Name"] = "workwolf-daemon"
        return response
