import base64

from flask import Flask, jsonify, request
from google import genai
from google.genai.types import Content, Part, GenerateContentConfigOrDict
import time
from werkzeug.wrappers import Request, Response, ResponseStream

app = Flask(__name__)


@app.before_request
def log_request():
    try:
        app.logger.debug('Request: %s', request.get_json())
    except:
        pass


@app.after_request
def log_response(response):
    if app.route == "/images/generations":
        return response
    try:
        app.logger.debug('Response: %s', response.get_json())
    except:
        pass
    return response


def get_client(request):
    try:
        authorization = request.headers['Authorization'].split(' ')
        if authorization is not None:
            client = genai.Client(api_key=authorization[1])
            return client
    except:
        return None


def get_chat_config(request):
    return {"max_output_tokens": request.json.get(
        'max_tokens'),
        "candidate_count": request.json.get(
            'n')}


@app.route('/models', methods=['GET'])
def models():
    client = get_client(request)
    list_of_models = {"data": [{"id": model.name, "object": "model"} for model in client.models.list()]}
    return jsonify(list_of_models)


@app.route('/completions', methods=['POST'])
def completion():
    client = get_client(request)
    config = get_chat_config(request)
    response_genai = client.models.generate_content(model=request.json.get('model'),
                                                    contents=request.json.get('prompt'), config=config)
    app.logger.debug('response_genai: %s', format(response_genai))
    choices = []
    for idx, candidate in enumerate(response_genai.candidates):
        text = ""
        for part in candidate.content.parts:
            text += part.text
        choices.append({
            "index": idx,
            "text": text,
            "finish_reason": candidate.finish_reason
        })
    response = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": response_genai.model_version,
        "choices": choices,
        "usage": {
            "prompt_tokens": response_genai.usage_metadata.prompt_token_count,
            "completion_tokens": response_genai.usage_metadata.candidates_token_count,
            "total_tokens": response_genai.usage_metadata.prompt_token_count
        }
    }
    return jsonify(response)


@app.route('/chat/completions', methods=['POST'])
def chat_completions():
    client = get_client(request)
    messages = request.json.get('messages')
    system = None
    history: list[Content] = []
    user_message = None
    for message in messages:
        if user_message is not None:
            history.append(Content(parts=[Part(text=user_message)], role="user"))
            user_message = None
        if message['role'] == 'system':
            system = message['content']
        elif message['role'] == 'user':
            user_message = message['content']
        else:
            history.append(Content(role=message['role'], parts=[Part(text=message['content'])]))
    if user_message is None:
        user_message = ""
    config = get_chat_config(request)
    config["system_instruction"] = system
    chat = client.chats.create(model=request.json.get('model'), history=history, config=config)
    response_genai = chat.send_message(Part(text=user_message))
    app.logger.debug('response_genai: %s', format(response_genai))
    choices = []
    for idx, candidate in enumerate(response_genai.candidates):
        text = ""
        for part in candidate.content.parts:
            text += part.text
        choices.append({
            "index": idx,
            "message": {
                "role": "assistant",
                "content": text,
                "refusal": None,
            },
            "finish_reason": candidate.finish_reason
        })
    response = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response_genai.model_version,
        "choices": choices,
        "usage": {
            "prompt_tokens": response_genai.usage_metadata.prompt_token_count,
            "completion_tokens": response_genai.usage_metadata.candidates_token_count,
            "total_tokens": response_genai.usage_metadata.prompt_token_count
        }
    }
    return jsonify(response)


@app.route('/images/generations', methods=['POST'])
def images():
    client = get_client(request)
    genai_response = client.models.generate_images(
        model=request.json.get('model'),
        prompt=request.json.get('prompt'),
        config={"number_of_images": request.json.get('n'),
                "person_generation": 'ALLOW_ADULT'})
    response = {"created": int(time.time()),
                "data": [{"b64_json": base64.b64encode(image.image.image_bytes).decode('utf-8')} for image in
                         genai_response.generated_images]}
    app.logger.debug('response_genai: %s', format(response))

    return jsonify(response)


if __name__ == '__main__':
    app.run()
