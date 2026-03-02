from app.api.v1.routes import router
for route in router.routes:
    print(route.path)
