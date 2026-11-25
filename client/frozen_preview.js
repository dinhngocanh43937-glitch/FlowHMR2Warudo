/* Fetch one cached first frame per capture session; never poll the image. */
class FrozenPreview {
  constructor(fetchFrame, show, clear) {
    this.fetchFrame = fetchFrame;
    this.show = show;
    this.clear = clear;
    this.session = null;
    this.done = false;
    this.loading = false;
    this.attempts = 0;
  }
  observe(client) {
    const session = client.preview_session;
    if (!session) return;
    if (session !== this.session) {
      this.session = session;
      this.done = false;
      this.attempts = 0;
      this.clear();
    }
    if (!client.preview_ready || this.done || this.loading || this.attempts >= 3) return;
    this.loading = true;
    this.attempts++;
    Promise.resolve().then(() => this.fetchFrame(session)).then(async response => {
      if (response.status !== 200) throw new Error('First frame not ready');
      const blob = await response.blob();
      if (this.session !== session) return;
      this.show(blob);
      this.done = true;
    }).catch(() => {}).finally(() => { this.loading = false; });
  }
}
if (typeof module !== 'undefined') module.exports = FrozenPreview;
else window.FrozenPreview = FrozenPreview;
