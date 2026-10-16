# Model settings editor

The model dialog groups connection details, Thinking/sampling, output budget and
reliability settings. Token controls are visible without opening advanced options.
Quick values include 2,048, 8,192, 32,000, 65,536 and 131,072. The editor shows an
active-settings summary, and its header/actions stay visible while scrolling.
The settings page has jump links for Chat, receipts, the lab and personal settings.

## Numeric entry and provider defaults

The editor keeps raw numeric input separate from the saved integer token value.
Clearing the number field no longer becomes the sentinel `0`, disables the field or
selects provider-default mode. Empty, fractional, negative and out-of-range token
inputs are blocked by native form validation. Valid token counts are 64 through
2,147,483,647; choosing provider-default explicitly saves `0`. Switching modes inside
the editor preserves the custom number. The API continues to validate saved values.

Provider-default means the application omits the output-limit parameter; it does not
mean infinite output, the maximum model context or even the model's maximum output.
The provider may apply a lower default. Monthly Cloud budget reservation still needs
an explicit output limit. Reading images in Inbox retains its separately documented
4,096-token extraction budget; Chat and text extraction respect the configured value.

## Thinking and Temperature

The application no longer disables sampling just because a Thinking level is selected.
Ollama, Custom compatible APIs, OpenRouter and Gemini requests include the configured
Temperature alongside the selected reasoning parameter. Native OpenAI reasoning model
requests and Groq requests with explicit Thinking retain their previous sampling-default
behavior; the editor explains the inactive field and retains its stored value. No
parameter is silently removed and retried after API rejection. Provider/model support
still varies, and a server can reject an unsupported effort or parameter combination.

Primary references:
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [OpenRouter request parameters](https://openrouter.ai/docs/api_reference/parameters)

New UI-created models start with 8,192 output tokens / 45s for Chat and 4,096 / 30s
for extraction. Existing saved models are not rewritten. API defaults remain unchanged.

Tests cover clearing and typing 32000 character by character, switching modes, presets,
reloading saved settings, sampling availability and retained values across providers,
plus actual mock HTTP request bodies containing Thinking, Temperature and token limits.
No private keys or financial data are required for these regression tests.
