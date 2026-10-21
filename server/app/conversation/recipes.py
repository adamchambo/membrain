"""Fixed server-owned recipe per interpreted action; the model never chooses tools."""

from app.conversation import learning, practice
from app.conversation.processor import bank

RECIPES = {
    "bank": bank,
    "recall": learning.recall,
    "teach": learning.teach,
    "adopt": learning.adopt,
    "diagnose": learning.diagnose,
    "practice": practice.start,
    "answer": practice.answer,
    "stop": practice.stop,
    "help": learning.help_reply,
}
