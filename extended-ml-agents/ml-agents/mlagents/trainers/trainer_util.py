import os
import yaml
from typing import Any, Dict, TextIO

from mlagents_envs.logging_util import get_logger
from mlagents.trainers.meta_curriculum import MetaCurriculum
from mlagents.trainers.exception import TrainerConfigError
from mlagents.trainers.trainer import Trainer
from mlagents.trainers.exception import UnityTrainerException
from mlagents.trainers.ppo.trainer import PPOTrainer
from mlagents.trainers.sac.trainer import SACTrainer
from mlagents.trainers.ghost.trainer import GhostTrainer
from mlagents.trainers.ghost.controller import GhostController


logger = get_logger(__name__)


class TrainerFactory:
    def __init__(
        self,
        trainer_config: Any,
        summaries_dir: str,
        run_id: str,
        model_path: str,
        keep_checkpoints: int,
        train_model: bool,
        load_model: bool,
        seed: int,
        init_path: str = None,
        meta_curriculum: MetaCurriculum = None,
        multi_gpu: bool = False,
    ):
        self.trainer_config = trainer_config
        self.summaries_dir = summaries_dir
        self.run_id = run_id
        self.model_path = model_path
        self.init_path = init_path
        self.keep_checkpoints = keep_checkpoints
        self.train_model = train_model
        self.load_model = load_model
        self.seed = seed
        self.meta_curriculum = meta_curriculum
        self.multi_gpu = multi_gpu
        self.ghost_controller = GhostController()

    def generate(self, brain_name: str, mydemopath : str) -> Trainer:   # Teo mydemopath:added
        return initialize_trainer(
            mydemopath,     # Teo mydemopath: added
            self.trainer_config,
            brain_name,
            self.summaries_dir,
            self.run_id,
            self.model_path,
            self.keep_checkpoints,
            self.train_model,
            self.load_model,
            self.ghost_controller,
            self.seed,
            self.init_path,
            self.meta_curriculum,
            self.multi_gpu,
        )


def initialize_trainer(
    mydemopath: str,        # Teo mydemopath: added
    trainer_config: Any,
    brain_name: str,
    summaries_dir: str,
    run_id: str,
    model_path: str,
    keep_checkpoints: int,
    train_model: bool,
    load_model: bool,
    ghost_controller: GhostController,
    seed: int,
    init_path: str = None,
    meta_curriculum: MetaCurriculum = None,
    multi_gpu: bool = False,
) -> Trainer:
    """
    Initializes a trainer given a provided trainer configuration and brain parameters, as well as
    some general training session options.

    :param trainer_config: Original trainer configuration loaded from YAML
    :param brain_name: Name of the brain to be associated with trainer
    :param summaries_dir: Directory to store trainer summary statistics
    :param run_id: Run ID to associate with this training run
    :param model_path: Path to save the model
    :param keep_checkpoints: How many model checkpoints to keep
    :param train_model: Whether to train the model (vs. run inference)
    :param load_model: Whether to load the model or randomly initialize
    :param ghost_controller: The object that coordinates ghost trainers
    :param seed: The random seed to use
    :param init_path: Path from which to load model, if different from model_path.
    :param meta_curriculum: Optional meta_curriculum, used to determine a reward buffer length for PPOTrainer
    :return:
    """
    if "default" not in trainer_config and brain_name not in trainer_config:
        raise TrainerConfigError(
            f'Trainer config must have either a "default" section, or a section for the brain name ({brain_name}). '
            "See config/trainer_config.yaml for an example."
        )

    trainer_parameters = trainer_config.get("default", {}).copy()
    trainer_parameters["summary_path"] = str(run_id) + "_" + brain_name
    trainer_parameters["model_path"] = "{basedir}/{name}".format(
        basedir=model_path, name=brain_name
    )
    if init_path is not None:
        trainer_parameters["init_path"] = "{basedir}/{name}".format(
            basedir=init_path, name=brain_name
        )
    trainer_parameters["keep_checkpoints"] = keep_checkpoints
    if brain_name in trainer_config:
        _brain_key: Any = brain_name
        while not isinstance(trainer_config[_brain_key], dict):
            _brain_key = trainer_config[_brain_key]
        trainer_parameters.update(trainer_config[_brain_key])

    min_lesson_length = 1
    if meta_curriculum:
        if brain_name in meta_curriculum.brains_to_curricula:
            min_lesson_length = meta_curriculum.brains_to_curricula[
                brain_name
            ].min_lesson_length
        else:
            logger.warning(
                f"Metacurriculum enabled, but no curriculum for brain {brain_name}. "
                f"Brains with curricula: {meta_curriculum.brains_to_curricula.keys()}. "
            )

    # Teo Thesis
    print("-------------> Trainer Parameters: ", trainer_parameters)
    trainer_parameters["behavioral_cloning"]["demo_path"] = mydemopath
    trainer_parameters["reward_signals"]["gail"]["demo_path"] = mydemopath
    print("-------------> (ΑΦΤΕΡ) Trainer Parameters: ", trainer_parameters)
    # end Teo Thesis


    trainer: Trainer = None  # type: ignore  # will be set to one of these, or raise
    if "trainer" not in trainer_parameters:
        raise TrainerConfigError(
            f'The "trainer" key must be set in your trainer config for brain {brain_name} (or the default brain).'
        )
    trainer_type = trainer_parameters["trainer"]

    if trainer_type == "offline_bc":
        raise UnityTrainerException(
            "The offline_bc trainer has been removed. To train with demonstrations, "
            "please use a PPO or SAC trainer with the GAIL Reward Signal and/or the "
            "Behavioral Cloning feature enabled."
        )
    elif trainer_type == "ppo":
        trainer = PPOTrainer(
            brain_name,
            min_lesson_length,
            trainer_parameters,
            train_model,
            load_model,
            seed,
            run_id,
        )
    elif trainer_type == "sac":
        trainer = SACTrainer(
            brain_name,
            min_lesson_length,
            trainer_parameters,
            train_model,
            load_model,
            seed,
            run_id,
        )

    else:
        raise TrainerConfigError(
            f'The trainer config contains an unknown trainer type "{trainer_type}" for brain {brain_name}'
        )

    if "self_play" in trainer_parameters:
        trainer = GhostTrainer(
            trainer,
            brain_name,
            ghost_controller,
            min_lesson_length,
            trainer_parameters,
            train_model,
            run_id,
        )
    

    return trainer


def load_config(config_path: str) -> Dict[str, Any]:
    try:
        with open(config_path) as data_file:
            return _load_config(data_file)
    except IOError:
        abs_path = os.path.abspath(config_path)
        raise TrainerConfigError(f"Config file could not be found at {abs_path}.")
    except UnicodeDecodeError:
        raise TrainerConfigError(
            f"There was an error decoding Config file from {config_path}. "
            f"Make sure your file is save using UTF-8"
        )


def _load_config(fp: TextIO) -> Dict[str, Any]:
    """
    Load the yaml config from the file-like object.
    """
    try:
        return yaml.safe_load(fp)
    except yaml.parser.ParserError as e:
        raise TrainerConfigError(
            "Error parsing yaml file. Please check for formatting errors. "
            "A tool such as http://www.yamllint.com/ can be helpful with this."
        ) from e


def handle_existing_directories(
    model_path: str, summary_path: str, resume: bool, force: bool, init_path: str = None
) -> None:
    """
    Validates that if the run_id model exists, we do not overwrite it unless --force is specified.
    Throws an exception if resume isn't specified and run_id exists. Throws an exception
    if --resume is specified and run-id was not found.
    :param model_path: The model path specified.
    :param summary_path: The summary path to be used.
    :param resume: Whether or not the --resume flag was passed.
    :param force: Whether or not the --force flag was passed.
    """

    model_path_exists = os.path.isdir(model_path)

    if model_path_exists:
        if not resume and not force:
            raise UnityTrainerException(
                "Previous data from this run ID was found. "
                "Either specify a new run ID, use --resume to resume this run, "
                "or use the --force parameter to overwrite existing data."
            )
    else:
        if resume:
            raise UnityTrainerException(
                "Previous data from this run ID was not found. "
                "Train a new run by removing the --resume flag."
            )

    # Verify init path if specified.
    if init_path is not None:
        if not os.path.isdir(init_path):
            raise UnityTrainerException(
                "Could not initialize from {}. "
                "Make sure models have already been saved with that run ID.".format(
                    init_path
                )
            )
