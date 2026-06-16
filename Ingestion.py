import langchain 
import langchain_core
import langchain_community
import langchain_qdrant
import langgraph
from langchain_google_genai import GoogleGenerativeAI
import os 
from dotenv import load_dotenv 
from langchain_community.document_loaders import PyMuPDFLoader 
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from langgraph.graph import StateGraph, START, END
from typing import TypedDict,List,Dict, Any, Annotated, Option, Union 


load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") 









































































