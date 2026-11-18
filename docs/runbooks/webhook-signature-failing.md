# The webhook signature is failing

## What you see

The API logs `whatsapp_signature_refused` and answers Meta with 401. No WhatsApp message is stored, so no customer on WhatsApp gets a reply, while the web chat keeps working. Meta's dashboard shows the webhook deliveries failing.

## What it means

The signature Meta sends with each notification did not match the HMAC-SHA256 of the body under the app secret the API holds. Either the secret is wrong or the request is not from Meta.

- Every notification fails, starting at a deploy or at a change in Meta's dashboard: the app secret was rotated there and not here, or the API was given the secret of another app.
- A few fail and most pass: someone is posting to the endpoint. That is the check doing its job. The address of a webhook is not a secret.
- Every notification fails and nothing changed: something between Meta and the API is rewriting the body. The signature is over the exact bytes Meta sent.

## What to do

For a rotated secret, put the current one in the vault under `whatsapp-app-secret` and restart the API, which reads it at start. Meta delivers a failed notification again, "immediately, then a few more times with decreasing frequency over the next 7 days", so the messages that were refused arrive once the secret is right. They are stored once however many times they come.

Do not make the check lenient to get messages flowing. An endpoint that accepts unsigned notifications lets anyone write messages into any tenant's conversations.

The other half of the subscription is the verify token: if Meta cannot confirm the webhook when it is saved in the dashboard, the API answers 403 and the value to compare is `whatsapp-verify-token`.

## Not rehearsed

All of it. The adapter has only met the payloads in Meta's documentation. Whether Meta signs the raw bytes exactly as the API reads them is one of the open questions in docs/verificado.md, and the first real notification answers it.
