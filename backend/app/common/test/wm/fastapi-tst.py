from fastapi import FastAPI


app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Index"}


@app.post("/")
async def root1():
    return {"message": "Post root"}


@app.get("/user")
async def hello(name: str = "Stranger"):
    return {"message": f"Hello, {name}!"}
