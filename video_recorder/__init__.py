import streamlit.components.v1 as components

_component_func = components.declare_component(
    "video_recorder",
    path="./video_recorder/frontend",
)

def video_recorder():
    return _component_func()
