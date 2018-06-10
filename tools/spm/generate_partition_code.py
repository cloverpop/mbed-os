#!/usr/bin/python
import glob
import itertools
import json
import os
from os.path import join as path_join

from jinja2 import Environment, FileSystemLoader
from jsonschema import validate

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = path_join(SCRIPT_DIR, 'templates')
MANIFEST_TEMPLATES = filter(
    lambda filename: '_NAME_' in filename,
    glob.glob(path_join(TEMPLATES_DIR, '*.tpl'))
)
COMMON_TEMPLATES = filter(
    lambda filename: '_NAME_' not in filename,
    glob.glob(path_join(TEMPLATES_DIR, '*.tpl'))
)
MANIFEST_FILE_PATTERN = '*_psa.json'


def assert_int(num):
    """
    Tries to parse an integer num from a given string

    :param num: Number in int/string type
    :return: Numeric value
    """
    if isinstance(num, int):
        return num
    num_str = str(num)
    radix = 16 if num_str.lower().startswith('0x') else 10
    res = int(num_str, radix)
    # Python converts str to int as a signed integer
    if res > 0x7FFFFFFF:
        res -= 0x100000000
    return res


class RotService(object):
    MINOR_POLICIES = ['STRICT', 'RELAXED']

    def __init__(
            self,
            name,
            identifier,
            signal,
            non_secure_clients,
            minor_version=1,
            minor_policy='STRICT'
    ):
        """
        Root of Trust Service C'tor (Aligned with json schema)

        :param name: Root of Trust Service identifier (available to user)
        :param identifier: Root of Trust Service numeric enumeration.
        :param signal: Root of Trust Service identifier inside the partition
        :param non_secure_clients: True to allow connections from non-secure
               partitions
        :param minor_version: Root of Trust Service version
        :param minor_policy: Enforcement level of minor version
        """
        self.name = name
        self.id = identifier
        self.signal = signal

        assert assert_int(identifier)

        assert isinstance(non_secure_clients, bool), \
            'non_secure_clients parameter must be of boolean type'
        self.nspe_callable = non_secure_clients

        self.minor_version = assert_int(minor_version)
        assert self.minor_version > 0, 'minor_version parameter is invalid'

        assert minor_policy in self.MINOR_POLICIES, \
            'minor_policy parameter is invalid'
        self.minor_policy = minor_policy

    @property
    def numeric_id(self):
        return assert_int(self.id)

    def __eq__(self, other):
        return (
            (self.name == other.name) and
            (self.id == other.id) and
            (self.signal == other.signal) and
            (self.nspe_callable == other.nspe_callable) and
            (self.minor_version == other.minor_version) and
            (self.minor_policy == other.minor_policy)
        )


class MmioRegion(object):
    MMIO_PERMISSIONS = {
        'READ-ONLY': 'PSA_MMIO_PERM_READ_ONLY',
        'READ-WRITE': 'PSA_MMIO_PERM_READ_WRITE'
    }

    def __init__(self, **kwargs):
        """
        MMIO Region C'tor (Aligned with json schema)

        Supports both named and numeric regions
        In case of named region the acceptable params are name and permission
        In case of numeric region the acceptable params are name, size and
        permission

        :param name: C definition name of the region (size will be
                     auto-generated)
        :param base: C hex string defining a memory address (must be 32bit)
        :param size: size of a region (Applicable only for numbered regions)
        :param permission: Access permissions to the described region (R/RW)

        """
        assert 'permission' in kwargs
        self.permission = self.MMIO_PERMISSIONS[kwargs['permission']]
        if 'name' in kwargs:
            self.base = kwargs['name']
            self.size = '(sizeof(*({})))'.format(kwargs['name'])
        if 'base' in kwargs:
            self.base = kwargs['base']
            self.size = assert_int(kwargs['size'])

        assert hasattr(self, 'base')
        assert hasattr(self, 'size')
        assert hasattr(self, 'permission')

    def __eq__(self, other):
        return (
            (self.base == other.base) and
            (self.size == other.size) and
            (self.permission == other.permission)
        )


class Irq(object):
    def __init__(self, line_num, signal):
        """
        IRQ line C'tor (Aligned with json schema)

        :param line_num: number of interrupt used by the partition
        :param signal: IRQ line identifier inside the partition
        """
        self.line_num = assert_int(line_num)
        assert isinstance(signal, basestring)
        self.signal = signal

    def __eq__(self, other):
        return (self.line_num == other.line_num) and \
               (self.signal == other.signal)


class Manifest(object):
    PRIORITY = {
        'LOW': 'osPriorityLow',
        'NORMAL': 'osPriorityNormal',
        'HIGH': 'osPriorityHigh'
    }
    PARTITION_TYPES = ['APPLICATION-ROT', 'PSA-ROT']

    def __init__(
            self,
            manifest_file,
            name,
            partition_id,
            partition_type,
            priority,
            entry_point,
            heap_size,
            stack_size,
            source_files,
            mmio_regions=None,
            rot_services=None,
            extern_sids=None,
            irqs=None
    ):
        """
        Manifest C'tor (Aligned with json schema)

        :param manifest_file: Path to json manifest
        :param name: Partition unique name
        :param partition_id: Partition identifier
        :param partition_type: Whether the partition is unprivileged or part
               of the trusted computing base
        :param priority: Priority of the partition's thread
        :param entry_point: C symbol name of the partition's main function
        :param heap_size: Size of heap required for the partition
        :param stack_size: Size of stack required for the partition
        :param source_files: List of files assembling the partition
               (relative paths)
        :param mmio_regions: List of MMIO regions used by the partition
        :param rot_services: List of Root of Trust Services declared by the
               partition
        :param extern_sids: List of Root of Trust Services the partition can call
        :param irqs: List of interrupts the partition can handle
        """
        assert manifest_file is not None
        assert name is not None
        assert partition_id is not None
        assert partition_type is not None
        assert entry_point is not None
        assert priority is not None
        assert heap_size is not None
        assert stack_size is not None
        assert source_files is not None

        mmio_regions = [] if mmio_regions is None else mmio_regions
        rot_services = [] if rot_services is None else rot_services
        extern_sids = [] if extern_sids is None else extern_sids
        irqs = [] if irqs is None else irqs

        assert os.path.isfile(manifest_file)
        assert isinstance(partition_id, (int, long))
        assert isinstance(heap_size, int)
        assert isinstance(stack_size, int)
        assert isinstance(entry_point, basestring)
        assert partition_type in self.PARTITION_TYPES
        assert partition_id > 0

        self.file = manifest_file
        self.name = name
        self.id = partition_id
        self.type = partition_type
        self.priority = self.PRIORITY[priority]
        self.heap_size = heap_size
        self.stack_size = stack_size
        self.entry_point = entry_point
        if isinstance(source_files, list):
            self.source_files = source_files
        else:
            self.source_files = [source_files]

        self.mmio_regions = mmio_regions
        self.rot_services = rot_services
        self.extern_sids = extern_sids
        self.irqs = irqs

        for src_file in self.source_files:
            assert os.path.isfile(src_file), \
                "The source file {} mentioned in {} doesn't exist.".format(
                    src_file, self.file
                )

        for rot_srv in self.rot_services:
            assert isinstance(rot_srv, RotService)

        for extern_sid in self.extern_sids:
            assert isinstance(extern_sid, basestring)

        assert len(self.extern_sids) == len(set(self.extern_sids)), \
            'Detected duplicates external SIDs in {}'.format(self.file)

        for irq in self.irqs:
            assert isinstance(irq, Irq)

        assert len(self.rot_services) + len(self.irqs) > 0,\
            'Manifest {} - {} does not contain at least 1 IRQ or ROT_SRV'.format(
                self.name, self.file
            )

    def __eq__(self, other):
        return (
            (self.file == other.file) and
            (self.name == other.name) and
            (self.id == other.id) and
            (self.type == other.type) and
            (self.priority == other.priority) and
            (self.heap_size == other.heap_size) and
            (self.stack_size == other.stack_size) and
            (self.entry_point == other.entry_point) and
            (self.source_files == other.source_files) and
            (self.mmio_regions == other.mmio_regions) and
            (self.rot_services == other.rot_services) and
            (self.extern_sids == other.extern_sids) and
            (self.irqs == other.irqs)
        )

    @classmethod
    def from_json(cls, manifest_file, skip_src=False):
        """
        Load a partition manifest file

        :param manifest_file: Manifest file path
        :param skip_src: Ignore the `source_files` entry
        :return: Manifest object
        """

        partition_schema_path = path_join(
            SCRIPT_DIR,
            'partition_description_schema.json'
        )
        with open(partition_schema_path) as schema_fh:
            partition_schema = json.load(schema_fh)

        # Load partition manifest file.
        with open(manifest_file) as fh:
            manifest = json.load(fh)

        validate(manifest, partition_schema)
        manifest_dir = os.path.dirname(manifest_file)

        source_files = []
        if not skip_src:
            for src_file in manifest['source_files']:
                source_files.append(
                    os.path.normpath(path_join(manifest_dir, src_file)))

        mmio_regions = []
        for mmio_region in manifest.get('mmio_regions', []):
            mmio_regions.append(MmioRegion(**mmio_region))

        rot_services = []
        for rot_srv in manifest.get('services', []):
            rot_services.append(RotService(**rot_srv))

        irqs = []
        for irq in manifest.get('irqs', []):
            irqs.append(Irq(**irq))

        return Manifest(
            manifest_file=manifest_file,
            name=manifest['name'],
            partition_id=assert_int(manifest['id']),
            partition_type=manifest['type'],
            priority=manifest['priority'],
            heap_size=assert_int(manifest['heap_size']),
            stack_size=assert_int(manifest['stack_size']),
            entry_point=manifest['entry_point'],
            source_files=source_files,
            mmio_regions=mmio_regions,
            rot_services=rot_services,
            extern_sids=manifest.get('extern_sids', []),
            irqs=irqs
        )

    @property
    def sids(self):
        return [rot_srv.name for rot_srv in self.rot_services]

    @property
    def autogen_folder(self):
        return path_join(os.path.dirname(self.file), 'psa_partition_autogen')

    def is_up_to_date(self, template_files):
        """
        Check if need to re-generate source files

        We don't need to re-generate the files if:
        1. All the expected generated files exist AND
        2. None of the JSON, templates, script files were modified after the
           auto-generated files

        :param template_files: List of the template files
        :return: True/False
        """

        return is_up_to_date(
            [self.file],
            template_files,
            list(self.templates_to_files(template_files,
                                         self.autogen_folder).values())
        )

    def find_dependencies(self, manifests):
        """
        Find other manifests which holds Root of Trust Services that
        are declared as extern in this manifest

        :param manifests: list of manifests to filter
        :return: list of manifest's names that holds current
                extern Root of Trust Services
        """

        manifests = filter(lambda man: man != self, manifests)
        extern_sids_set = set(self.extern_sids)
        return [manifest.name for manifest in manifests
                if extern_sids_set.intersection(set(manifest.sids))]

    def templates_to_files(self, templates, output_dir):
        """
        Translates a list of partition templates to file names

        :param templates: List of partition templates
        :param output_dir: Output directory (Default is autogen folder property)
        :return: Dictionary of template to output file translation
        """

        generated_files = {}
        for t in templates:
            fname = os.path.basename(t)
            _tpl = fname.replace('NAME', self.name.lower())
            full_path = path_join(
                output_dir,
                os.path.splitext(_tpl)[0]
            )
            generated_files[t] = full_path

        return generated_files


def check_circular_call_dependencies(manifests):
    """
    Check if there is a circular dependency between the partitions described by the manifests.
    A circular dependency might happen if there is a scenario in which a partition calls a Root of Trust Service in another
    partition which than calls another Root of Trust Service which resides in the originating partition.
    For example: Partition A has a Root of Trust Service A1 and extern sid B1, partition B has a Root of Trust Service B1 and
                 extern sid A1.

    :param manifests: List of the partition manifests.
    :return: True if a circular dependency exists, false otherwise.
    """

    # Construct a call graph.
    call_graph = {}
    for manifest in manifests:
        call_graph[manifest.name] = {
            'calls': manifest.find_dependencies(manifests),
            'called_by': set()
        }
    for manifest_name in call_graph:
        for called in call_graph[manifest_name]['calls']:
            call_graph[called]['called_by'].add(manifest_name)

    # Run topological sort on the call graph.
    while len(call_graph) > 0:
        # Find all the nodes that aren't called by anyone and
        # therefore can be removed.
        nodes_to_remove = filter(lambda x: len(call_graph[x]['called_by']) == 0, call_graph.keys())

        # If no node can be removed we have a circle.
        if not nodes_to_remove:
            return True

        # Remove the nodes.
        for node in nodes_to_remove:
            for called in call_graph[node]['calls']:
                call_graph[called]['called_by'].remove(node)
            call_graph.pop(node)

    return False


def validate_partition_manifests(manifests):
    """
    Check the correctness of the manifests list
    (no conflicts, no missing elements, etc.)

    :param manifests: List of the partition manifests
    """
    for manifest in manifests:
        assert isinstance(manifest, Manifest)

    partitions_names = {}
    partitions_ids = {}
    rot_service_ids = {}
    rot_service_names = {}
    rot_service_signals = {}
    irq_signals = {}
    irq_numbers = {}

    for manifest in manifests:
        # Make sure the partition names are unique.
        if manifest.name in partitions_names:
            raise ValueError(
                'Partition name {} is not unique, '
                'found in both {} and {}.'.format(
                    manifest.name,
                    partitions_names[manifest.name],
                    manifest.file
                )
            )
        partitions_names[manifest.name] = manifest.file

        # Make sure the partition ID's are unique.
        if manifest.id in partitions_ids:
            raise ValueError(
                'Partition id {} is not unique, '
                'found in both {} and {}.'.format(
                    manifest.id,
                    partitions_ids[manifest.id],
                    manifest.file
                )
            )
        partitions_ids[manifest.id] = manifest.file

        # Make sure all the Root of Trust Service IDs and signals are unique.
        for rot_service in manifest.rot_services:
            if rot_service.name in rot_service_names:
                raise ValueError(
                    'Root of Trust Service name {} is found '
                    'in both {} and {}.'.format(
                        rot_service.name,
                        rot_service_names[rot_service.name],
                        manifest.file
                    )
                )
            rot_service_names[rot_service.name] = manifest.file

            if rot_service.signal in rot_service_signals:
                raise ValueError(
                    'Root of Trust Service signal {} is found '
                    'in both {} and {}.'.format(
                        rot_service.signal,
                        rot_service_signals[rot_service.signal],
                        manifest.file
                    )
                )
            rot_service_signals[rot_service.signal] = manifest.file

            if rot_service.numeric_id in rot_service_ids:
                raise ValueError(
                    'Root of Trust Service identifier {} is found '
                    'in both {} and {}.'.format(
                        rot_service.numeric_id,
                        rot_service_ids[rot_service.numeric_id],
                        manifest.file
                    )
                )
            rot_service_ids[rot_service.numeric_id] = manifest.file

        # Make sure all the IRQ signals and line-numbers are unique.
        for irq in manifest.irqs:
            if irq.signal in irq_signals:
                raise ValueError(
                    'IRQ signal {} is found in both {} and {}.'.format(
                        irq.signal,
                        irq_signals[irq.signal],
                        manifest.file
                    )
                )
            irq_signals[irq.signal] = manifest.file

            if irq.line_num in irq_numbers:
                raise ValueError(
                    'IRQ line number {} is found in both {} and {}.'.format(
                        irq.line_num,
                        irq_numbers[irq.line_num],
                        manifest.file
                    )
                )
            irq_numbers[irq.line_num] = manifest.file

    # Check that all the external SIDs can be found.
    declared_sids = set(rot_service_names.keys())
    for manifest in manifests:
        extern_sids = set(manifest.extern_sids)
        if not extern_sids.issubset(declared_sids):
            missing_sids = extern_sids.difference(declared_sids)
            raise ValueError(
                "External SID(s) {} required by {} can't be found in "
                "any partition manifest.".format(
                    ', '.join(missing_sids), manifest.file)
            )

    if check_circular_call_dependencies(manifests):
        raise ValueError("Detected a circular call dependency between the partitions.")


def get_latest_timestamp(*files):
    """
    Scan a list of files and return the latest modification time

    :param files: List of files to be scanned
    :return: Latest modification time from all the files
    """
    return max([os.path.getmtime(f) for f in files])


def is_up_to_date(manifest_files, template_files, generated_files):
    """
    Check if need to re-generate source files

    We don't need to re-generate the files if:
    1. All the expected generated files exist AND
    2. None of the XMLs, templates, script files were modified after the
       auto-generated files

    :param manifest_files: List of the manifest files
    :param template_files: List of the template files
    :param generated_files: List of the generated files
    :return: True/False
    """
    num_of_partitions = len(manifest_files)
    num_of_partition_templates = len(
        list(filter(lambda filename: '_NAME_' in filename, template_files))
    )

    num_of_common_templates = len(template_files) - num_of_partition_templates

    expected_num_of_generated_files = \
        (num_of_partitions * num_of_partition_templates) + \
        num_of_common_templates

    for f in generated_files:
        if not os.path.exists(f):
            return False

    if expected_num_of_generated_files == len(generated_files):
        timestamp_generated = get_latest_timestamp(*generated_files)
        timestamp_src = get_latest_timestamp(
            __file__, *(template_files + manifest_files)
        )
        if timestamp_generated > timestamp_src:
            return True
    return False


def generate_source_files(
        templates,
        render_args,
        output_folder,
        extra_filters=None
):
    """
    Generate SPM common C code from manifests using given templates

    :param templates: Dictionary of template and their auto-generated products
    :param render_args: Dictionary of arguments that should be passed to render
    :param output_folder: Output directory for file generation
    :param extra_filters: Dictionary of extra filters to use in the rendering
           process
    :return: Path to generated folder containing common generated files
    """

    rendered_files = []
    templates_dirs = list(
        set([os.path.dirname(path) for path in templates])
    )
    template_files = {os.path.basename(t): t for t in templates}

    # Load templates for the code generation.
    env = Environment(
        loader=FileSystemLoader(templates_dirs),
        lstrip_blocks=True,
        trim_blocks=True
    )
    if extra_filters:
        env.filters.update(extra_filters)

    for tf in template_files:
        template = env.get_template(tf)
        rendered_files.append(
            (templates[template_files[tf]], template.render(**render_args)))

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for fname, data in rendered_files:
        with open(fname, 'wt') as fh:
            fh.write(data)

    return output_folder


def generate_partitions_sources(manifest_files, extra_filters=None):
    """
    Process all the given manifest files and generate C code from them

    :param manifest_files: List of manifest files
    :param extra_filters: Dictionary of extra filters to use in the rendering
           process
    :return: List of paths to the generated files
    """

    # Construct a list of all the manifests and sids.
    manifests = []
    for manifest_file in manifest_files:
        manifest = Manifest.from_json(manifest_file)
        manifests.append(manifest)

    generated_folders = []
    for manifest in manifests:
        manifest_output_folder = manifest.autogen_folder
        if not manifest.is_up_to_date(MANIFEST_TEMPLATES):
            render_args = {
                'partition': manifest,
                'dependent_partitions': manifest.find_dependencies(manifests)
            }
            manifest_output_folder = generate_source_files(
                manifest.templates_to_files(MANIFEST_TEMPLATES,
                                            manifest_output_folder),
                render_args,
                manifest_output_folder,
                extra_filters=extra_filters
            )
            generated_folders.append(manifest_output_folder)

    return generated_folders


def generate_spm_data(manifest_files, output_dir, extra_filters=None):
    """
Process all the given manifest files and generate C code from them
    :param manifest_files: List of manifest files
    :param output_dir: Output directory for the generated source files
    :param extra_filters: Dictionary of extra filters to use in the rendering
           process
    :return: List of paths to the generated files
    """
    autogen_folder = path_join(output_dir, 'psa_autogen')
    templates_dict = {
        t: path_join(autogen_folder, os.path.basename(os.path.splitext(t)[0]))
        for t in COMMON_TEMPLATES
    }

    complete_source_list = templates_dict.values()

    # Construct lists of all the manifests and mmio_regions.
    region_list = []
    manifests = []
    for manifest_file in manifest_files:
        manifest_obj = Manifest.from_json(manifest_file)
        manifests.append(manifest_obj)
        for region in manifest_obj.mmio_regions:
            region_list.append(region)
        complete_source_list.extend(
            manifest_obj.templates_to_files(
                MANIFEST_TEMPLATES,
                manifest_obj.autogen_folder).values()
        )

    # Validate the correctness of the manifest collection.
    validate_partition_manifests(manifests)

    if is_up_to_date(
            manifest_files,
            MANIFEST_TEMPLATES + COMMON_TEMPLATES,
            complete_source_list):
        return autogen_folder

    render_args = {
        'partitions': manifests,
        'region_pair_list': list(itertools.combinations(region_list, 2))
    }

    return generate_source_files(
        templates_dict,
        render_args,
        autogen_folder,
        extra_filters=extra_filters
    )