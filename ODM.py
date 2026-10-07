__author__ = 'Pablo Ramos Criado'
__students__ = 'Pablo_Alferez_Serrano__Rafael_Ceres_Martinez'


from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import time
from typing import Generator, Any, Self
from geojson import Point
import pymongo
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
import yaml

def getLocationPoint(address: str) -> Point:
    """ 
    Obtiene las coordenadas de una dirección en formato geojson.Point
    Utilizar la API de geopy para obtener las coordenadas de la direccion
    Cuidado, la API es publica tiene limite de peticiones, utilizar sleeps.

    Parameters
    ----------
        address : str
            direccion completa de la que obtener las coordenadas
    Returns
    -------
        geojson.Point
            coordenadas del punto de la direccion
    """
    location = None
    intentos = 0
    maxIntentos = 5
    while location is None and intentos < maxIntentos:
        intentos += 1
        try:
            time.sleep(1)
            # Es necesario proporcionar un user_agent para utilizar la API
            # Utilizar un nombre aleatorio para el user_agent
            location = Nominatim(user_agent="RafaCM").geocode(address)
        except GeocoderTimedOut:
            # Puede lanzar una excepcion si se supera el tiempo de espera
            # Volver a intentarlo
            continue
    if(location is not None):
        return Point((location.longitude, location.latitude))
    else:
        raise ValueError("No se pudieron obtener coordenadas")
    # Devolver un GeoJSON de tipo punto con la latitud y longitud almacenadas.
    # Si no se consiguieron coordenadas, lanzar ValueError: la funcion no puede
    # devolver un punto inventado ni None silenciosamente. Es lo que espera la
    # prueba test_get_location_point_timeout_failure.


class Model:
    """ 
    Clase de modelo abstracta
    Crear tantas clases que hereden de esta clase como  
    colecciones/modelos se deseen tener en la base de datos.

    Attributes
    ----------
        required_vars : set[str]
            conjunto de atributos requeridos por el modelo
        admissible_vars : set[str]
            conjunto de atributos admitidos por el modelo
        db : pymongo.collection.Collection
            conexion a la coleccion de la base de datos
    
    Methods
    -------
        __setattr__(name: str, value: str | dict) -> None
            Sobreescribe el metodo de asignacion de valores a los 
            atributos del objeto con el fin de controlar qué atributos 
            son modificados y cuando son modificados.
        __getattr__(name: str) -> Any
            Sobreescribe el metodo de acceso a atributos del objeto 
        save()  -> None
            Guarda el modelo en la base de datos
        delete() -> None
            Elimina el modelo de la base de datos
        find(filter: dict[str, str | dict]) -> ModelCursor
            Realiza una consulta de lectura en la BBDD.
            Devuelve un cursor de modelos ModelCursor
        aggregate(pipeline: list[dict]) -> pymongo.command_cursor.CommandCursor
            Devuelve el resultado de una consulta aggregate.
        find_by_id(id: str) -> dict | None
            Busca un documento por su id utilizando la cache y lo devuelve.
            Si no se encuentra el documento, devuelve None.
        init_class(db_collection: pymongo.collection.Collection, required_vars: set[str], admissible_vars: set[str]) -> None
            Inicializa las variables de clase en la inicializacion del sistema.

    """
    _required_vars: set[str]
    _admissible_vars: set[str]
    _location_var: str | None = None
    _db: pymongo.collection.Collection
    _internal_vars: set[str] = frozenset(('_modified_vars', '_required_vars', '_admissible_vars', '_db', '_data', '_location_var'))

    def __init__(self, **kwargs: dict[str, str | dict | list]) -> None:
        """
        Inicializa el modelo con los valores proporcionados en kwargs
        Comprueba que los valores proporcionados en kwargs son admitidos
        por el modelo y que las atributos requeridos son proporcionadas.
    
        Parameters
        ----------
            kwargs : dict[str, str | dict]
                    diccionario con los valores de las atributos del modelo
        """
        self._data: dict[str, str | dict | list] = {}
        # Realizar las comprabociones y gestiones necesarias
        # antes de la asignacion.
    
        vars_set = self._required_vars | self._admissible_vars

        vars_set.add("_id")
        
        if self._location_var:
            vars_set.add(f"{self._location_var}_loc")
    
        if(not self._required_vars.issubset(set(kwargs.keys()))):
            raise ValueError(f"Las variables {set(self._required_vars).difference(set(kwargs.keys()))} no se han proporcionado.")
    
        if(not set(kwargs.keys()).issubset(vars_set)):
            raise ValueError(f"{set(kwargs.keys()).difference(vars_set)} no son variables de este modelo.")
    
                    
    
        # Asigna todos los valores en kwargs a las atributos con 
        # nombre las claves en kwargs
        # Utilizamos el atributo data para guardar los variables 
        # almacenadas en la base de datos en una solo atributo
        # Encapsular los datos en una sola variable facilita la 
        # gestion en metodos como save.
        self._data.update(kwargs)

    def __setattr__(self, name: str, value: str | dict) -> None:
        """ Sobreescribe el metodo de asignacion de valores a los 
        atributos del objeto con el fin de controlar que atributos 
        son modificados y cuando son modificados.
        """
        if name in self._internal_vars:
            super().__setattr__(name, value)
            return
        
        # Realizar las comprabociones y gestiones necesarias
        # antes de la asignacion.
        if(name not in self._admissible_vars and name not in self._required_vars):
            raise ValueError(f"La variable {name} no existe.")

        #Si la variable es de localización, crea la variable loc y la asigna
        if(self._location_var and name == self._location_var):
            coords = getLocationPoint(value)
            name_loc = f"{name}_loc"
            self._data[name_loc] = coords
    
        # Asigna el valor value a la variable name
        self._data[name] = value

    def __getattr__(self, name: str) -> Any:
        """ Sobreescribe el metodo de acceso a atributos del objeto
        __getattr__ solo es llamado cuando no encuentra el atributo
        en el objeto 
        """
        if name in self._internal_vars:
            return super().__getattribute__(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError
        
    def save(self) -> None:
        """
        Guarda el modelo en la base de datos
        Si el modelo no existe en la base de datos, se crea un nuevo
        documento con los valores del modelo. En caso contrario, se
        actualiza el documento existente con los nuevos valores del
        modelo.
        """

        # Aqui lo que hago es comprobar si existe una variable de localizacion en el modelo y si existe lo convierto a coordenadas con el getLocationPoint
        if(self._location_var and self._location_var in self._data):
            self._data[f"{self._location_var}_loc"] = getLocationPoint(self._data[self._location_var])

        
        #Si el objeto ya existe
        if("_id" in self._data and self._data["_id"] is not None):
            self._db.replace_one({"_id": self._data["_id"]}, self._data)
        else:
            self._db.insert_one(self._data)

    def delete(self) -> None:
        """
        Elimina el modelo de la base de datos
        """
        if(self._data["_id"] is None):
            raise ValueError("El modelo no existe en la base de datos.")
        
        self._db.delete_one( {"_id":self._data["_id"]} )
    
    @classmethod
    def find(cls, filter: dict[str, str | dict]) -> Any:
        """ 
        Utiliza el metodo find de pymongo para realizar una consulta
        de lectura en la BBDD.
        find debe devolver un cursor de modelos ModelCursor

        Parameters
        ----------
            filter : dict[str, str | dict]
                diccionario con el criterio de busqueda de la consulta
        Returns
        -------
            ModelCursor
                cursor de modelos
        """ 

        # cls es el puntero a la clase
        cursor_pymongo = cls._db.find(filter)
        return ModelCursor(cls, cursor_pymongo)

    @classmethod
    def aggregate(cls, pipeline: list[dict]) -> pymongo.command_cursor.CommandCursor:
        """ 
        Devuelve el resultado de una consulta aggregate. 
        No hay nada que hacer en esta funcion.
        Se utilizara para las consultas solicitadas
        en el segundo proyecto de la practica.

        Parameters
        ----------
            pipeline : list[dict]
                lista de etapas de la consulta aggregate 
        Returns
        -------
            pymongo.command_cursor.CommandCursor
                cursor de pymongo con el resultado de la consulta
        """ 
        return cls._db.aggregate(pipeline)
    
    @classmethod
    def find_by_id(cls, id: str) -> Self | None:
        """ 
        NO IMPLEMENTAR HASTA EL TERCER PROYECTO
        Busca un documento por su id utilizando la cache y lo devuelve.
        Si no se encuentra el documento, devuelve None.

        Parameters
        ----------
            id : str
                id del documento a buscar
        Returns
        -------
            Self | None
                Modelo del documento encontrado o None si no se encuentra
        """ 
        #TODO
        pass

    @classmethod
    def init_class(cls, db_collection: pymongo.collection.Collection, indexes:dict[str,str], required_vars: set[str], admissible_vars: set[str]) -> None:
        """ 
        Inicializa los atributos de clase en la inicializacion del sistema.
        Aqui se deben inicializar o asegurar los indices. Tambien se puede
        alguna otra inicialización/comprobaciones o cambios adicionales
        que estime el alumno.

        Parameters
        ----------
            db_collection : pymongo.collection.Collection
                Conexion a la collecion de la base de datos.
            indexes: Dict[str,str]
                Set de indices y tipo de indices para la coleccion
            required_vars : set[str]
                Set de atributos requeridos por el modelo
            admissible_vars : set[str] 
                Set de atributos admitidos por el modelo
        """
        cls._db = db_collection
        cls._required_vars = set(required_vars)
        cls._admissible_vars = set(admissible_vars)
        # Recorrer indexes y crear cada índice segun su tipo: 'unique', 'asc'
        # y 'geosphere'. Comparar el tipo por igualdad, no con el operador 'in'.
        # Ojo con el índice geoespacial: save() guarda el GeoJSON Point en
        # <campo>_loc, luego el índice 2dsphere va sobre <campo>_loc, mientras
        # que _location_var debe guardar el nombre del campo base.
        for nombreIndice, atributos in indexes.items():
            if(nombreIndice == "unique_indexes"):
                for atributo in atributos:
                    db_collection.create_index([(atributo, 1)], unique=True)
            elif(nombreIndice == "regular_indexes"):
                for atributo in atributos:
                    db_collection.create_index([(atributo, 1)])
            elif(nombreIndice == "location_indexes"):
                if atributos:
                    if isinstance(atributos, str):
                        atributos = [atributos]

                    for atributo in atributos:
                        db_collection.create_index(
                            [(atributo + "_loc", "2dsphere")]
                        )
                        cls._location_var = atributo

            

class ModelCursor:
    """ 
    Cursor para iterar sobre los documentos del resultado de una
    consulta. Los documentos deben ser devueltos en forma de objetos
    modelo.

    Attributes
    ----------
        model_class : Model
            Clase para crear los modelos de los documentos que se iteran.
        cursor : pymongo.cursor.Cursor
            Cursor de pymongo a iterar

    Methods
    -------
        __iter__() -> Generator
            Devuelve un iterador que recorre los elementos del cursor
            y devuelve los documentos en forma de objetos modelo.
    """

    def __init__(self, model_class: Model, cursor: pymongo.cursor.Cursor):
        """
        Inicializa el cursor con la clase de modelo y el cursor de pymongo

        Parameters
        ----------
            model_class : Model
                Clase para crear los modelos de los documentos que se iteran.
            cursor: pymongo.cursor.Cursor
                Cursor de pymongo a iterar
        """
        self.model = model_class
        self.cursor = cursor
    
    def __iter__(self) -> Generator:
        """
        Devuelve un iterador que recorre los elementos del cursor
        y devuelve los documentos en forma de objetos modelo.
        Utilizar yield para generar el iterador
        Utilizar la funcion next para obtener el siguiente documento del cursor
        Utilizar alive para comprobar si existen mas documentos.
        """
        while(self.cursor.alive):
            doc = next(self.cursor)
            yield self.model(**doc)


def initApp(definitions_path: str = "./models.yml", mongodb_uri="mongodb://localhost:27017/", db_name="abd", scope=globals()) -> None:
    """ 
    Declara las clases que heredan de Model para cada uno de los 
    modelos de las colecciones definidas en definitions_path.
    Inicializa las clases de los modelos proporcionando los indices y 
    atributos admitidos y requeridos para cada una de ellas y la conexión a la
    collecion de la base de datos.
    
    Parameters
    ----------
        definitions_path : str
            ruta al fichero de definiciones de modelos
        mongodb_uri : str
            uri de conexion a la base de datos
        db_name : str
            nombre de la base de datos
    """
    # Inicializar base de datos
    cliente = MongoClient(mongodb_uri)
    db = cliente[db_name]

    # Declarar tantas clases modelo colecciones existan en la base de datos
    # Leer el fichero de definiciones de modelos para obtener las colecciones,
    # indices y los atributos admitidos y requeridos para cada una de ellas.
    # Ejemplo de declaracion de modelo para colecion llamada MiModelo
    # scope["MiModelo"] = type("MiModelo", (Model,),{})

    try:
        # Abro el archivo de definiciones en modo lectura con r
        with open(definitions_path, 'r') as archivoModels:
            # yaml.safe_load transforma el texto del YAML en un diccionario de Python
            definiciones = yaml.safe_load(archivoModels)


            for nombre_Modelo, atributos in definiciones.items():
                scope[nombre_Modelo] = type(nombre_Modelo, (Model,), {})

                indices = {
                    "unique_indexes" : atributos.get("unique_indexes", []),
                    "regular_indexes": atributos.get("regular_indexes", []),
                    "location_indexes" : atributos.get("location_index", None)
                }


                # La clase se declara en tiempo de ejecucion y queda en scope, que no tiene
                # por que ser el espacio de nombres global: las pruebas le pasan su propio
                # diccionario. Por eso se inicializa a traves de scope y no por su nombre,
                # que ahi todavia no existe.
                #scope["MiModelo"].init_class(db_collection=None, indexes=None, required_vars=None, admissible_vars=None)    
                scope[nombre_Modelo].init_class(db_collection=db[nombre_Modelo], indexes=indices, required_vars=atributos.get("required_vars", []), admissible_vars=atributos.get("admissible_vars", []))

    except Exception as e:
        print(f"Error al procesar el archivo: {e}")
        return


if __name__ == '__main__':
    
    # Inicializar base de datos y modelos con initApp
    initApp()

    # Hacer pruebas para comprobar que funciona correctamente el modelo
    
    # Crear modelo
    pepe = Artista(nombre="Pepe", generos = ["Rock"], paisOrigen = "Portugal")

    # Asignar nuevo valor a variable admitida del objeto 
    pepe.paisOrigen = "España"

    # Asignar nuevo valor a variable no admitida del objeto 
    #pepe.ciudadOrigen = "Madrid"

    # Guardar
    pepe.save()

    # Asignar nuevo valor a variable admitida del objeto
    pepe.paisOrigen = "Francia"

    # Guardar
    pepe.save()

    # Buscar nuevo documento con find
    artistas = Artista.find({"nombre":"Pepe"})

    # Obtener primer documento
    artista = next(iter(artistas), None)

    # Modificar valor de variable admitida
    artista.paisOrigen = "España"

    # Guardar
    artista.save()