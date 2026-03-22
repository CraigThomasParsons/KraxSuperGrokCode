import os
import json
try:
    import pika
except ImportError:
    pika = None

def dispatch_package(sender_id: str, recipient_id: str, package_id: str, outbox_dir: str):
    """
    Finalizes the package delivery mechanism by writing the letter.toml
    and emitting the RabbitMQ signal for The Postal Service.
    It expects all payload files (like job.json) to already be written inside
    outbox_dir/package_id/.
    """
    package_dir = os.path.join(outbox_dir, package_id)
    os.makedirs(package_dir, exist_ok=True)
    
    # Write letter.toml for Postal Service routing
    with open(os.path.join(package_dir, "letter.toml"), "w") as f:
        f.write(f'recipient = "{recipient_id}"\n')
        f.write(f'package_id = "{package_id}"\n')
        
    if not pika:
        print(f"[PostalService] ERROR: Python pika library missing. Cannot deliver {package_id}")
        return

    try:
        credentials = pika.PlainCredentials('postalWorker', 'D0n74G37Me')
        connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost', credentials=credentials))
        channel = connection.channel()
        channel.exchange_declare(exchange='postal.signals', exchange_type='topic', durable=True)
        message = {
            "event": "package_ready",
            "sender": sender_id,
            "package_id": package_id
        }
        channel.basic_publish(
            exchange='postal.signals',
            routing_key='signal.ready',
            body=json.dumps(message),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        print(f"[PostalService] Signaled {package_id} from {sender_id} to {recipient_id}")
    except Exception as e:
        print(f"[PostalService] Warning: Failed to emit AMQP signal for {package_id}: {e}")
