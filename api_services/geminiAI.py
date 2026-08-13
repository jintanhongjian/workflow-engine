from google import genai  #google-genai
from openai import OpenAI
import os, io, time, sys, base64
from google.genai import types,errors
import filetype as fty
from PIL import Image
from io import BytesIO
import requests as req
from enum import Enum
from pydantic import BaseModel

class jsonList(BaseModel):
    key: str
    value: str|list[str]

class text(BaseModel):
    text:str

class IMG_READ(Enum):
    READ = 0
    URL = 1
    UPLOAD = 2
class IMG_OUTPUT(Enum):
    Bytes=0
    Base64=1
    
class MODEL_TYPE(Enum):
    content="gemini-2.5-flash"
    contpro="gemini-2.5-pro"
    genImage2="gemini-2.0-flash-preview-image-generation"
    trsAudio="gemini-2.5-flash-preview-tts"
    genImage3="imagen-3.0-generate-002"
    genVeo="veo-3.0-generate-preview"

class TaskType(Enum):
    # "RETRIEVAL_QUERY" : "Specifies the given text is a query in a search/retrieval setting."
    RETR_QUERY="RETRIEVAL_QUERY"
    # "RETRIEVAL_DOCUMENT":	"Specifies the given text is a document in a search/retrieval setting."
    RETR_DOC="RETRIEVAL_DOCUMENT"
    # "SEMANTIC_SIMILARITY": "Specifies the given text will be used for Semantic Textual Similarity (STS)."
    SEMA_SIMI="SEMANTIC_SIMILARITY"
    # "CLASSIFICATION":	"Specifies that the embeddings will be used for classification."
    CLASSIFY="CLASSIFICATION"
    # "CLUSTERING":	"Specifies that the embeddings will be used for clustering."
    CLUSTER="CLUSTERING"
    
project_dir=os.path.dirname(sys.argv[0])

class GmiAI_Tool():
    def __init__(self):
        Auto_Process_AI_Api_Key="AIzaSyDD0A9pa2LphT49G3cN8WBu_0AJYPWkY9A"
        jt_AI_Api_Key="AIzaSyBLOWCkhtGlBt4ndeft-MwVaVouVmaUUkk"
        self.Gemini_client = genai.Client(api_key=Auto_Process_AI_Api_Key)

    def getUploadFiles(self):
        try:
            client_files=self.Gemini_client.files.list()
            for f in client_files:
                print(' ', f.name)
            return client_files
        except errors.ClientError as err:
            print(err.message)
            return err        

    def startChat(self,thinkBudget=0,sysInstruction="",modelType:MODEL_TYPE=MODEL_TYPE.content):
        try:
            self.model=modelType
            if modelType==MODEL_TYPE.content:
                content_config=types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(thinking_budget=thinkBudget), # Disables thinking
                            system_instruction=sysInstruction)
                self.chat=self.Gemini_client.chats.create(model=modelType.value,config=content_config)
                return "chat started with {modelType}"
            if modelType==MODEL_TYPE.genImage2:
                image_config=types.GenerateContentConfig(
                            response_modalities=['TEXT', 'IMAGE'])
                self.chat=self.Gemini_client.chats.create(model=modelType.value,config=image_config)
                return "chat started with {modelType}"       
        except errors.ClientError as err:
            print(err.message)
            return err
        

    def chatMessage(self,message):
        try:
            response = self.chat.send_message(message)
            if self.model==MODEL_TYPE.content.value:  
                return response.text
            if self.model==MODEL_TYPE.genImage2.value:
                des=""
                image=None
                for part in response.candidates[0].content.parts:
                    if part.text is not None:
                        des=part.text
                    elif part.inline_data is not None:
                        image = Image.open(BytesIO((part.inline_data.data)))
                        image.show()
                return des,image            
        except errors.APIError as err:
            print(err.message)
            return err            
            
    def getChatHistory(self):
        try:
            history=self.chat.get_history()
            for message in history:
                print(f'role - {message.role}', end=": ")
                print(message.parts[0].text)
            return history
        except errors.APIError as err:
            print(err.message)
            return err         
        
    def getModels(self):
        for m in self.Gemini_client.models.list():
            print(m.name)

    def imageLoad(self,imagePath,readType:IMG_READ=IMG_READ.READ,
                  output:IMG_OUTPUT=IMG_OUTPUT.Bytes):
        try:
            image=None
            if readType==IMG_READ.URL:
                image_bytes = req.get(imagePath).content
                imageType=fty.guess_mime(image_bytes)
                if output==IMG_OUTPUT.Bytes:
                    image = types.Part.from_bytes(
                    data=image_bytes, mime_type=imageType
                    )
                elif output==IMG_OUTPUT.Base64:
                    image=base64.b64encode(image_bytes).decode('utf-8')
            if readType==IMG_READ.READ:
                with open(imagePath, 'rb') as f:
                    image_bytes = f.read()
                imageType=fty.guess_mime(image_bytes)
                if output==IMG_OUTPUT.Bytes:
                    image = types.Part.from_bytes(
                    data=image_bytes, mime_type=imageType
                    )
                elif output==IMG_OUTPUT.Base64:
                    image=base64.b64encode(image_bytes).decode('utf-8')
            if readType==IMG_READ.UPLOAD:
                image = self.Gemini_client.files.upload(file=imagePath)
            return image
        except errors.APIError as err:
            print(err.message)
            return err         
            
    def gmContent(self,content,sysInstr="",thought=False,thinkBudget=0,respType="text/plain",schema=text):
        try:
            response = self.Gemini_client.models.generate_content(
                model=MODEL_TYPE.content.value, 
                contents=content,
                config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(include_thoughts=thought,
                            thinking_budget=thinkBudget), 
                        system_instruction=sysInstr,
                        response_mime_type=respType,response_schema=schema),
            )
            # print(response)
            return response.text
        except errors.APIError as err:
            print(err.message)
            return err         
        
    def gmStreamContent(self,content,sysInstr="",thought=False,thinkBudget=0):
        try:
            response = self.Gemini_client.models.generate_content_stream(
                model=MODEL_TYPE.content.value, 
                contents=content,
                config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(include_thoughts=thought,
                            thinking_budget=thinkBudget), 
                        system_instruction=sysInstr),
            )
            # print(response)
            # for chunk in response:
            #     print(chunk.text,end=" ")
            return response
        except errors.APIError as err:
            print(err.message)
            return err         
        
    def gmGenerateImage(self,prompt,imageSavePath):
        try:
            response = self.Gemini_client.models.generate_content(
                model=MODEL_TYPE.genImage2.value,
                contents=prompt,
                config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE']
                )
            )
            des=""
            image=None
            for part in response.candidates[0].content.parts:
                if part.text is not None:
                    des=part.text
                elif part.inline_data is not None:
                    image = Image.open(BytesIO((part.inline_data.data)))
                    image.save(imageSavePath)
                    image.show()
            return des,image
        except errors.APIError as err:
            print(err.message)
            return err         
        
    def gmModifyImage(self,prompt,imagePaths:list,imageSavePath,readType:IMG_READ=IMG_READ.READ):
        try:
            # text_input = ('Hi, This is a picture of me.'
            #             'Can you add a llama next to me?')
            images=[]
            for imgFile in imagePaths:
                image=self.imageLoad(imgFile,readType,output=IMG_OUTPUT.Bytes)
                images.append(image)
            response = self.Gemini_client.models.generate_content(
                model=MODEL_TYPE.genImage2.value,
                contents=[prompt, *images],
                config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE']
                )
            )
            des=""
            image=None
            for part in response.candidates[0].content.parts:
                if part.text is not None:
                    des=part.text
                elif part.inline_data is not None:
                    image = Image.open(BytesIO((part.inline_data.data)))
                    image.save(imageSavePath)
                    image.show()
            return des,image
        except errors.APIError as err:
            print(err.message)
            return err         


    def gmExtractFile(self,prompt,filePath:str):
        # Upload the file to the File API
        file = self.Gemini_client.files.upload(file=filePath, config={'display_name': filePath.split('/')[-1].split('.')[0]})
        # Generate a structured response using the Gemini API
        response = self.Gemini_client.models.generate_content(model=MODEL_TYPE.content.value, 
                                                              contents=[prompt, file], 
        )
        # Convert the response to the pydantic model and return it
        print(response.text)
        return response.text        
        
    def gmReadImage(self,prompt,imagePaths:list,readType:IMG_READ=IMG_READ.READ):
        try:
            images=[]
            for imgFile in imagePaths:
                image=self.imageLoad(imgFile,readType,output=IMG_OUTPUT.Bytes)
                images.append(image)
            response = self.Gemini_client.models.generate_content(
                model=MODEL_TYPE.content.value,
                contents=[prompt,*images]
            )
            print(response.text)
            return response.text
        except errors.APIError as err:
            print(err.message)
            return err         

    def gmReadVedio(self,vedioPath,prompt):
        try:
            myfile = self.Gemini_client.files.upload(file=vedioPath)
            response = self.Gemini_client.models.generate_content(
                model=MODEL_TYPE.content.value, 
                contents=[myfile, prompt])
            print(response.text)
            return response.text
        except errors.APIError as err:
            print(f"Error: {err}")
            result={"response":"error","content":err}
            return result            

    def gmCreateVedio(self,prompt,savePath,naPrompt="",startFromImage=False):
        try:
            if startFromImage:
                imagen = self.Gemini_client.models.generate_images(
                    model=MODEL_TYPE.genImage3.value,
                    prompt=prompt,
                ) 
                startImage=imagen.generated_images[0].image
            else:
                startImage=None       
            operation = self.Gemini_client.models.generate_videos(
                model=MODEL_TYPE.genVeo.value,
                prompt=prompt,
                image=startImage,
                config=types.GenerateVideosConfig(negative_prompt=naPrompt,),
            )
            operation = types.GenerateVideosOperation(name=operation.name)
            # Poll the operation status until the video is ready.
            while not operation.done:
                print("Waiting for video generation to complete...")
                time.sleep(10)
                operation = self.Gemini_client.operations.get(operation)

            # Download the generated video.
            generated_video = operation.response.generated_videos[0]
            self.Gemini_client.files.download(file=generated_video.video)
            generated_video.video.save(savePath)
            print("Generated video saved to mp4")          
        except errors.APIError as err:
            print(f"Error: {err}")
            result={"response":"error","content":err}
            return result        

    def gmEmbedAnalysis(self,contents,task:TaskType) -> any:
        try:
            result = self.Gemini_client.models.embed_content(model="gemini-embedding-001",
                                                    contents=contents,
                                                    config=types.EmbedContentConfig(
                                                        task_type=task))
            return result.embeddings[0].values
        except errors.APIError as err:
            print(f"Error: {err}")
            result={"response":"error","content":err}
            return result   

class OpenAI_Tool():
    def __init__(self):
        Auto_Process_AI_Api_Key="AIzaSyDf-AyhK3jBj1DDrahhykE3Zz8qBKeZ98Y"
        jt_AI_Api_Key="AIzaSyBLOWCkhtGlBt4ndeft-MwVaVouVmaUUkk"
        self.OpenAI_client = OpenAI(
                            api_key=Auto_Process_AI_Api_Key,
                            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                        )

    def imageLoad(self,imagePath,readType:IMG_READ=IMG_READ.READ,
                  output:IMG_OUTPUT=IMG_OUTPUT.Bytes):
        try:
            image=None
            if readType==IMG_READ.URL:
                image_bytes = req.get(imagePath).content
                imageType=fty.guess_mime(image_bytes)
                if output==IMG_OUTPUT.Bytes:
                    image = types.Part.from_bytes(
                    data=image_bytes, mime_type=imageType
                    )
                elif output==IMG_OUTPUT.Base64:
                    image=base64.b64encode(image_bytes).decode('utf-8')
            if readType==IMG_READ.READ:
                with open(imagePath, 'rb') as f:
                    image_bytes = f.read()
                imageType=fty.guess_mime(image_bytes)
                if output==IMG_OUTPUT.Bytes:
                    image = types.Part.from_bytes(
                    data=image_bytes, mime_type=imageType
                    )
                elif output==IMG_OUTPUT.Base64:
                    image=base64.b64encode(image_bytes).decode('utf-8')
            return image
        except errors.APIError as err:
            print(err.message)
            return err     

    def getUploadFiles(self):
        try:
            client_files=self.OpenAI_client.files.list()
            for f in client_files:
                print(' ', f.name)
            return client_files
        except errors.ClientError as err:
            print(err.message)
            return err       

    def opContent(self,userContent,sysContent="",effort="low",isStream=False):
        try:
            response = self.OpenAI_client.chat.completions.create(
                model=MODEL_TYPE.content.value,
                reasoning_effort=effort,
                messages=[
                    {"role": "system", "content": sysContent},
                    {"role": "user","content": userContent}
                ],
                stream=isStream
            )
            if isStream:
                return response
            else:
                return response.choices[0]
        except errors.APIError as err:
            print(err.message)
            return err              
 

    def opReadImage(self,prompt,image_path,imageType:IMG_READ=IMG_READ.READ):
        try:
            base64_image = self.imageLoad(image_path,type=imageType,output=IMG_OUTPUT.Base64)
            response = self.OpenAI_client.chat.completions.create(
            model=MODEL_TYPE.content.value,
            messages=[
                {
                "role": "user",
                "content": [
                    {
                    "type": "text",
                    "text": prompt,
                    },
                    {
                    "type": "image_url",
                    "image_url": {
                        "url":  f"data:image/jpeg;base64,{base64_image}"
                    },
                    },
                ],
                }
            ],
            )
            return response.choices[0]
        except errors.APIError as err:
            print(err.message)
            return err         
 
    def opGenImage(self,prompt):
        response = self.OpenAI_client.images.generate(
        model=MODEL_TYPE.genImage3.value,
        prompt=prompt,
        response_format='b64_json',
        n=1,
        )

        image_data=BytesIO(base64.b64decode(response.data[0].b64_json))
        image = Image.open(image_data)
        image.show()
        return image_data
    

    # def func(self):
    #     try:
    #         pass
    #     except errors.APIError as err:
            # print(f"Error: {err}")
            # result={"response":"error","content":err}
            # return result         
 
        
gAI=GmiAI_Tool()
gAI.getModels()
des=gAI.gmContent("Please list the latest BYD company news from date 2025-01-01 with the url links")
# img1=project_dir+f"/images/cat1.jpeg"
# img2=project_dir+f"/images/squarrel.jpeg"
# img3=project_dir+f"/images/raccoon.jpeg"
# images=[img1,img2,img3]
# pdf=os.path.join(project_dir,"Dinner_invoice.pdf")
# des=gAI.gmExtractFile("请读取发票文件中的销售方名称，商品名称，数量，单价，金额，税额信息", pdf)
print(des)
