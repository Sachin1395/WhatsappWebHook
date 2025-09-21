import os
import json
from flask import Flask, request, jsonify, abort, render_template_string
from dotenv import load_dotenv

# Azure Communication Services
from azure.communication.messages import NotificationMessagesClient
from azure.communication.messages.models import TextNotificationContent

# OpenAI
from openai import AzureOpenAI

load_dotenv()
app = Flask(__name__)

# ------------------------
# Config
# ------------------------
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://whatsappmsgrespond.openai.azure.com/")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
subscription_key = os.getenv("AZURE_OPENAI_KEY")

logs = []


# ------------------------
# Azure ChatBot Class
# ------------------------
class AzureChatBot:
    def __init__(self, endpoint, api_key, api_version, deployment):
        self.client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        )
        self.deployment = deployment
        self.conversation = [{"role": "system", "content": "You are a helpful assistant."}]

    def chat(self, user_input: str) -> str:
        self.conversation.append({"role": "user", "content": user_input})
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=self.conversation,
            max_tokens=512,
            temperature=0.7,
        )
        reply = response.choices[0].message.content
        self.conversation.append({"role": "assistant", "content": reply})
        return reply


# ------------------------
# Message Sender Class
# ------------------------
class MessagesQuickstart:
    def __init__(self):
        self.connection_string = os.getenv("COMMUNICATION_SERVICES_CONNECTION_STRING")
        self.channelRegistrationId = os.getenv("WHATSAPP_CHANNEL_ID")

    def send_text_message(self, to_number: str, text: str):
        messaging_client = NotificationMessagesClient.from_connection_string(self.connection_string)
        text_options = TextNotificationContent(
            channel_registration_id=self.channelRegistrationId,
            to=[to_number],
            content=text,
        )
        message_responses = messaging_client.send(text_options)
        response = message_responses.receipts[0]
        if response is not None:
            msg = f"✅ Sent reply to {response.to}, id={response.message_id}"
            print(msg)
            logs.append(msg)
        else:
            msg = "❌ Failed to send reply"
            print(msg)
            logs.append(msg)


# ------------------------
# Webhook Listener
# ------------------------
@app.route("/eventgrid", methods=["POST"])
def eventgrid_listener():
    try:
        event = request.get_json()
        logs.append(f"📩 Incoming Event: {json.dumps(event)}")

        for e in event:
            event_type = e.get("eventType")

            if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
                validation_code = e["data"]["validationCode"]
                logs.append(f"🔑 Validation request received: {validation_code}")
                return jsonify({"validationResponse": validation_code})

            elif event_type == "Microsoft.Communication.AdvancedMessageReceived":
                data = e.get("data", {})
                from_number = data.get("from")
                message_body = data.get("content", "")

                if not from_number.startswith("+"):
                    from_number = f"+{from_number}"

                msg_log = f"📲 Incoming AdvancedMessage from {from_number}: {message_body}"
                print(msg_log)
                logs.append(msg_log)

                mq = MessagesQuickstart()
                bot = AzureChatBot(endpoint, subscription_key, api_version, deployment)

                reply = bot.chat(message_body)
                mq.send_text_message(from_number, reply)

        return "", 200

    except Exception as ex:
        err = f"❌ Error in webhook: {str(ex)}"
        print(err)
        logs.append(err)
        abort(400, str(ex))


# ------------------------
# Logs Page
# ------------------------
@app.route("/logs", methods=["GET"])
def show_logs():
    template = """
    <html>
        <head><title>Webhook Logs</title></head>
        <body>
            <h1>📜 Webhook Logs</h1>
            <ul>
            {% for log in logs %}
                <li>{{ log }}</li>
            {% endfor %}
            </ul>
        </body>
    </html>
    """
    return render_template_string(template, logs=logs)


@app.route("/", methods=["GET"])
def home():
    return "ACS WhatsApp Webhook & PDF Service 🚀. Check /logs.", 200


# ------------------------
# Run
# ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
