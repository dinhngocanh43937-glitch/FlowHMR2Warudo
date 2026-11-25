"""One preview image per user-started capture session, including reconnects."""


class FirstFramePreview:
    def __init__(self, callback):
        self.callback = callback
        self.needs_frame = True

    def __call__(self, data):
        if self.needs_frame and data:
            self.callback(data)
            self.needs_frame = False
