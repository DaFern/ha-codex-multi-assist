// Runs as a non-iframe HA custom panel, never through the add-on's native bridge.
const LAUNCH_PATH = "/voice-match-learning";
const idText = (value) => typeof value === "string" && /^[a-zA-Z0-9_-]{1,128}$/.test(value);
const profileId = (value) => typeof value === "string" && /^[a-z0-9][a-z0-9_-]{0,39}$/.test(value);

class VoiceMatchLaunchPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._generation = 0;
    this._sent = false;
    this._busy = false;
    this._connected = false;
    this._autoAttempted = false;
    this._expected = null;
    this._locked = false;
    const make = (tag, text) => {
      const element = document.createElement(tag);
      if (text) element.textContent = text;
      return element;
    };
    const style = make("style", `
      :host { display: block; padding: 20px; box-sizing: border-box; color: var(--primary-text-color); font: 16px system-ui; }
      main { max-width: 640px; margin: auto; } p, li { line-height: 1.5; overflow-wrap: anywhere; }
      button, a { font: inherit; min-height: 44px; padding: 10px 14px; margin: 8px 8px 8px 0; }
      button { cursor: pointer; } button:disabled { cursor: default; } a { display: inline-block; }
      #status { border-inline-start: 4px solid #03a9f4; padding: 12px; } details { margin-top: 20px; }
      summary { cursor: pointer; min-height: 44px; } h1 { font-size: 1.5rem; }
    `);
    const main = make("main");
    main.append(make("h1", "Voice Learning"));
    this._message = make("p", "Checking the Companion app…");
    this._message.id = "status";
    this._message.setAttribute("role", "status");
    this._message.setAttribute("aria-live", "polite");
    main.append(this._message);
    this._open = make("button", "Open Voice Learning");
    this._open.type = "button";
    this._open.disabled = true;
    this._open.addEventListener("click", () => this._start());
    main.append(this._open);
    main.append(make("p", "Opening Assist may turn on your microphone for the initial request. Learning still requires the spoken notice and your separate consent."));
    main.append(make("p", "Android may remember Voice Learning as your last-used assistant. Select your usual assistant again afterwards. Home Assistant's global default is not changed."));
    const fallback = make("details");
    fallback.append(make("summary", "If Assist doesn't open"));
    fallback.append(make("p", 'In the Android Companion app, open Assist and choose Voice Learning. Say “Learn my voice” and follow the spoken notice. In a retained paused conversation, follow its separate “Continue learning” confirmation. A new conversation needs fresh consent.'));
    fallback.append(make("p", "If the learning assistant is missing, ask an administrator to check the setup. Don't change the default assistant or use an ordinary assistant to record samples."));
    main.append(fallback);
    const home = make("a", "Back to Home Assistant");
    home.href = "/";
    main.append(home);
    this.shadowRoot.append(style, main);
    this._onVisibility = () => {
      if (document.hidden) {
        this._generation += 1;
        if (this._busy) this._status("The launch was interrupted. Nothing was retried. Return to Voice Match when you're ready.");
      }
    };
  }

  set hass(value) {
    if (this._hass && (value.user?.id !== this._hass.user?.id || value.connection !== this._hass.connection || value.auth !== this._hass.auth)) {
      this._generation += 1;
      if (this._busy) this._status("Your signed-in connection changed. Return to Voice Match and try from your own profile.");
    }
    this._hass = value;
    this._updateButton();
    this._maybeAuto();
  }

  connectedCallback() {
    this._connected = true;
    document.addEventListener("visibilitychange", this._onVisibility);
    if (window.top !== window || location.pathname !== LAUNCH_PATH) {
      this._locked = true;
      this._status("Open the Voice Learning launcher inside Home Assistant, not in an embedded page.");
      return;
    }
    if (location.hash) {
      try {
        const values = new URLSearchParams(location.hash.slice(1));
        if ([...values.keys()].length !== 3 || !["request", "user", "profile"].every(key => values.has(key))
            || !/^[0-9a-f]{32}$/.test(values.get("request")) || !idText(values.get("user")) || !profileId(values.get("profile"))) {
          throw new Error("Invalid navigation context");
        }
        // Comparison-only context, not authority to select another account.
        this._expected = { user: values.get("user"), profile: values.get("profile") };
        this._consume();
      } catch {
        this._locked = true;
        this._status("This launch link is invalid. Return to your own profile in Voice Match.");
      }
    } else if (history.state?.voiceMatchLaunchConsumed) {
      this._locked = true;
      this._status("This launch request has already been used. Reloading or going Back won't open Assist again. Use your Voice Match button for a new request.");
    } else {
      this._status("Open Voice Learning in the Android Companion app. Recording consent is requested separately.");
    }
    this._updateButton();
    this._maybeAuto();
  }

  disconnectedCallback() {
    this._connected = false;
    this._generation += 1;
    document.removeEventListener("visibilitychange", this._onVisibility);
  }

  _consume() {
    // Remove comparison IDs before any network discovery. No credentials or
    // recording capabilities belong in links/history, and none are accepted here.
    history.replaceState({ ...(history.state || {}), voiceMatchLaunchConsumed: true }, "", LAUNCH_PATH);
  }

  _status(text) {
    this._message.textContent = text;
    this._updateButton();
  }

  _native() {
    const external = this._hass?.auth?.external;
    return external?.config?.hasAssist === true && typeof external.fireMessage === "function" ? external : null;
  }

  _updateButton() {
    this._open.disabled = this._busy || this._sent || this._locked || !this._connected || !this._hass?.connected || !this._native();
  }

  _maybeAuto() {
    if (this._expected && !this._autoAttempted && !this._locked && this._connected && this._hass?.connected) {
      this._autoAttempted = true;
      void this._start();
    }
  }

  async _start() {
    if (this._busy || this._sent || this._locked || !this._connected) return;
    const hass = this._hass;
    const external = this._native();
    if (!external || !hass?.connected) {
      this._status("Native Assist isn't available here. Use the Android Companion app or the manual steps below.");
      return;
    }
    if (document.hidden || window.top !== window || location.pathname !== LAUNCH_PATH) return;
    const user = hass.user?.id;
    if (!idText(user) || (this._expected && this._expected.user !== user)) {
      this._locked = true;
      this._status("The signed-in account doesn't match the Voice Match button. Return to Voice Match using your own account.");
      return;
    }
    const generation = ++this._generation;
    this._busy = true;
    this._status("Checking your profile and learning assistant…");
    let timer;
    try {
      this._consume();
      const info = await Promise.race([
        hass.callWS({ type: "codex_assist/voice_learning/launch_info" }),
        new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error("Launch check timed out")), 16000); }),
      ]);
      if (generation !== this._generation || !this._connected || document.hidden || location.pathname !== LAUNCH_PATH
          || !this._hass.connected || this._hass.user?.id !== user || this._hass.connection !== hass.connection
          || this._hass.auth !== hass.auth || this._native() !== external) return;
      if (!info || info.user_id !== user || !profileId(info.profile_id) || !idText(info.pipeline_id)
          || ["preferred", "last_used"].includes(info.pipeline_id)
          || (this._expected && info.profile_id !== this._expected.profile)) {
        this._locked = true;
        this._status("Your profile or learning assistant changed. Return to Voice Match and check your own profile.");
        return;
      }
      // assist/show has no acknowledgement. Mark sent BEFORE calling: a thrown
      // or lost response must never cause an automatic second native launch.
      this._sent = true;
      external.fireMessage({ type: "assist/show", payload: { pipeline_id: info.pipeline_id, start_listening: true } });
      this._status('Opening Voice Learning requested. If it appears, say “Learn my voice” to hear the notice. This page has not granted recording consent.');
    } catch {
      this._status(this._sent ? "The Assist opening request could not be verified. Check your phone; it has not been retried."
        : "Your learning setup could not be verified. Check your own profile, the enabled companion and the learning assistant. Nothing has been launched by this request.");
    } finally {
      clearTimeout(timer);
      this._busy = false;
      this._updateButton();
    }
  }
}

if (!customElements.get("voice-match-launch-panel")) customElements.define("voice-match-launch-panel", VoiceMatchLaunchPanel);
