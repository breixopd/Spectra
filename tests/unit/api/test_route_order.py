from spectra_api.api.routers.tools import router as tools_router


def test_tools_static_routes_precede_dynamic_tool_route() -> None:
    paths = [route.path for route in tools_router.routes]

    assert paths.index("/tools/for-ai") < paths.index("/tools/{tool_id}")
