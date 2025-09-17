import os
import json
from flask import Flask, request, jsonify, abort, render_template_string
from dotenv import load_dotenv

load_dotenv()

from azure.communication.messages import NotificationMessagesClient
from azure.communication.messages.models import TextNotificationContent

app = Flask(__name__)

# ------------------------
# Global Logs
# ------------------------
logs = []


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

        # EventGrid sends an array of events
        for e in event:
            event_type = e.get("eventType")

            # 1. Subscription validation handshake
            if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
                validation_code = e["data"]["validationCode"]
                logs.append(f"🔑 Validation request received: {validation_code}")
                return jsonify({"validationResponse": validation_code})

            # 2. Incoming ACS WhatsApp message
            elif event_type == "Microsoft.Communication.AdvancedMessageReceived":
                data = e.get("data", {})
                from_number = data.get("from")
                message_body = data.get("content", "")
            
                # ensure number has + prefix
                if not from_number.startswith("+"):
                    from_number = f"+{from_number}"
            
                msg_log = f"📲 Incoming AdvancedMessage from {from_number}: {message_body}"
                print(msg_log)
                logs.append(msg_log)
            
                # Send reply
                mq = MessagesQuickstart()
                mq.send_text_message(from_number, f"You said: {message_body}")


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
    return "ACS WhatsApp Webhook is running 🚀. Check /logs for activity.", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

