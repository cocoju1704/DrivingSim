# legacy

Kept for reference, not used by `takeover_experiment.py` any more.

- `gmailextension/`: the Gmail version of the NDRT (writing a notice e-mail). The Chrome extension sent
  the draft to ChatGPT for the RtR summary and talked to the experiment through `rtr_bridge.py`.
  Replaced by the KakaoTalk-style group chat `_Experiment/kakao_ndrt.py`, which serves the page and
  writes the RtR summary itself (same `request` / `result_since` / `status` interface).
