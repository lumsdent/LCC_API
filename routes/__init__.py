from flask import Blueprint

routes = Blueprint('routes', __name__)

from .players import *
from .matches import *
from .teams import *
from .practice import *