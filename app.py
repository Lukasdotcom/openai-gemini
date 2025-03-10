import base64

from flask import Flask, jsonify, request
from google import genai
from google.genai.types import Content, Part, FunctionDeclaration, Schema, Type, FunctionResponse, FunctionCall
import time
import random
import json
from werkzeug.wrappers import Response

app = Flask(__name__)


@app.before_request
def log_request():
    try:
        app.logger.debug('Request path: %s', request.path)
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


def convert_tools(tools):
    if tools is None:
        return []
    result: list[FunctionDeclaration] = []
    openai_to_gemini_types = {
        "string": Type.STRING,
        "integer": Type.INTEGER,
        "array": Type.ARRAY,
        "number": Type.NUMBER,
    }
    for tool in tools:
        properties = {}
        required = tool["function"]["parameters"].get('required', [])
        for key, value in tool["function"]["parameters"]["properties"].items():
            if value.get("type") is not None:
                properties[key] = Schema(type=openai_to_gemini_types[value["type"]])
                if value["type"] == 'array':
                    properties[key].items = Schema(type=openai_to_gemini_types[value["items"]["type"]])
            elif value.get('anyOf') is not None:
                any_of = []
                for item in value['anyOf']:
                    if item['type'] == 'null':
                        required.remove(key)
                        continue
                    any_of.append(Schema(type=openai_to_gemini_types[item["type"]]))
                    if item["type"] == 'array':
                        any_of[-1].items = Schema(type=openai_to_gemini_types[item["items"]["type"]])
                # Not that currently any_of is not supported by google ai so just using the first type
                properties[key] = any_of[0]
        new_tool = FunctionDeclaration(name=tool["function"]["name"])
        # Check if there are any properties given
        if len(properties) != 0:
            new_tool.parameters = Schema(description=tool["function"]["description"],
                                         type=Type.OBJECT,
                                         required=required,
                                         properties=properties)
        result.append(new_tool)
    app.logger.debug('Tools: %s', result)
    return [{"function_declarations": result}]


@app.route('/models', methods=['GET'])
def models():
    client = get_client(request)
    models = [{"id": model.name, "object": "model"} for model in client.models.list()]
    if len(models) == 0:
        return Response("No models found", status=400)
    list_of_models = {"data": models}
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
    for message in messages:
        if message.get('role') == 'system':
            system = message['content']
        elif message.get('role') == 'tool':
            history.append(Content(role='tool', parts=[Part(
                function_response=FunctionResponse(id=message['tool_call_id'], name=message["name"],
                                                   response={
                                                       "output": message["content"]
                                                   }))]))
        elif message.get('tool_calls') is not None:
            responses = []
            for tool_call in message['tool_calls']:
                function_call = FunctionCall(name=tool_call["function"]['name'], id=tool_call['id'])
                if len(json.loads(tool_call["function"]["arguments"])) > 0:
                    function_call.args = json.loads(tool_call["function"]["arguments"])
                responses.append(
                    Part(function_call=function_call))
            history.append(
                Content(parts=responses))
        else:
            history.append(Content(role=message['role'], parts=[
                Part(text=message['content'])]))
    config = get_chat_config(request)
    config["system_instruction"] = system
    config["tools"] = convert_tools(request.json.get('tools'))
    if len(history) == 0:
        return Response("No messages given", status=400)
    newest_message = history.pop()
    chat = client.chats.create(model=request.json.get('model'), history=history, config=config)
    response_genai = chat.send_message(newest_message.parts[0])
    app.logger.debug('response_genai: %s', format(response_genai))
    choices = []
    for idx, candidate in enumerate(response_genai.candidates):
        text = ""
        function_calls = []
        for part in candidate.content.parts:
            if part.text is not None:
                text += part.text
            elif part.function_call is not None:
                function_calls.append({"id": str(random.randint(0, 1000000)) + "_" + part.function_call.name,
                                       "type": "function",
                                       "function": {
                                           "name": part.function_call.name,
                                           "arguments": json.dumps(part.function_call.args)
                                       }})
        if len(function_calls) > 0:
            choices.append({
                "index": idx,
                "message": {
                    "role": "assistant",
                    "tool_calls": function_calls
                },
                "finish_reason": "tool_calls"
            })
        if len(text) > 0:
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
