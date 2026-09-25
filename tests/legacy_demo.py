"""Offline fixture for historical Tk behavior tests; never shipped in the app."""
from hdusign import gui as ui
from hdusign.demo import demo_courses, prepare_demo as write_demo


def prepare_demo(directory):
    ui.CONFIG = directory / 'config.yaml'
    ui.SECRETS = directory / 'secrets_local.json'
    write_demo(directory)


class DemoApp(ui.App):
    def __init__(self):
        super().__init__()
        self.refresh_live_courses()

    def _load_saved_live_courses(self):
        self._courses_job = None

    def refresh_live_courses(self):
        self._set_live_course_choices(demo_courses())
        self._select_live_course(next(iter(self._live_course_lookup)))
