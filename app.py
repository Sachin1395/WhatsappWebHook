import os
import json
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv

load_dotenv()

from azure.communication.messages import NotificationMessagesClient
from azure.communication.messages.models import TextNotificationContent

app = Flask(__name__)

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
            print(f"✅ WhatsApp message {response.message_id} sent to {response.to}")
        else:
            print("❌ Message failed to send")


# ------------------------
# Flask Webhook
# ------------------------
@app.route("/eventgrid", methods=["POST"])
def eventgrid_listener():
    try:
        event = request.get_json()
        print("📩 Incoming Event:", json.dumps(event, indent=2))

        # EventGrid sends an array of events
        for e in event:
            event_type = e.get("eventType")

            # 1. Subscription validation handshake
            if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
                validation_code = e["data"]["validationCode"]
                print("🔑 Subscription validation:", validation_code)
                return jsonify({"validationResponse": validation_code})

            # 2. Incoming ACS WhatsApp notification
            elif event_type == "Microsoft.Communication.ChatMessageReceived" or event_type == "Notification":
                data = e.get("data", {})
                from_number = data.get("from") or os.getenv("RECIPIENT_PHONE_NUMBER")
                message_body = data.get("messageBody", "Hello")

                print(f"📲 Message from {from_number}: {message_body}")

                # Send auto-reply
                mq = MessagesQuickstart()
                mq.send_text_message(from_number, "Thanks! We received your message.")

        return "", 200

    except Exception as ex:
        print("❌ Error in webhook:", str(ex))
        abort(400, str(ex))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
