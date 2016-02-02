"""
Based on https://github.com/django-haystack/django-haystack/commit/0fd8744aaf6294e10afd934acf2e1e8c0b5f474f#diff-86da7062c02bc3ba1fe14dd640207b78R288
which hasn't yet made it into a release as of 02/02/2016

Once the 'fuzzy' operator has been added to SearchQuerySet (which should be in the next release after 2.4.1) you should:
1) Change the HAYSTACK_CONNECTIONS setting to use the 'haystack.backends.elasticsearch_backend.ElasticsearchSearchEngine'
2) Delete this module/file
"""

WARN_AFTER_VERSION = (2, 4, 0)
VERSION_WARNING_MESSAGE = "The 'fuzzy' operator should now be included in the official django-haystack release." \
                          " Please follow the instructions at the top of service_directory.api.django-haystack_mod.py"

import haystack
import warnings

if haystack.__version__ > WARN_AFTER_VERSION:
    warnings.warn(VERSION_WARNING_MESSAGE)

from django.conf import settings
from django.utils import six
from haystack.backends.elasticsearch_backend import ElasticsearchSearchBackend, ElasticsearchSearchQuery, ElasticsearchSearchEngine
from haystack.constants import DEFAULT_OPERATOR, DJANGO_CT
from haystack.exceptions import MissingDependency
from haystack.inputs import Clean, PythonData, Exact, Raw
from haystack.utils import get_model_ct

try:
     import elasticsearch
     try:
         # let's try this, for elasticsearch > 1.7.0
         from elasticsearch.helpers import bulk
     except ImportError:
         # let's try this, for elasticsearch <= 1.7.0
         from elasticsearch.helpers import bulk_index as bulk
     from elasticsearch.exceptions import NotFoundError
except ImportError:
     raise MissingDependency("The 'elasticsearch' backend requires the installation of 'elasticsearch'. Please refer to the documentation.")


haystack.constants.FUZZY_MIN_SIM = getattr(
    settings, 'HAYSTACK_FUZZY_MIN_SIM', 0.5
)
haystack.constants.FUZZY_MAX_EXPANSIONS = getattr(
    settings, 'HAYSTACK_FUZZY_MAX_EXPANSIONS', 50
)

haystack.constants.VALID_FILTERS.add('fuzzy')


class FuzzyElasticsearchSearchBackend(ElasticsearchSearchBackend):
    def build_search_kwargs(self, query_string, sort_by=None, start_offset=0, end_offset=None,
                            fields='', highlight=False, facets=None,
                            date_facets=None, query_facets=None,
                            narrow_queries=None, spelling_query=None,
                            within=None, dwithin=None, distance_point=None,
                            models=None, limit_to_registered_models=None,
                            result_class=None):
        if haystack.__version__ > WARN_AFTER_VERSION:
            warnings.warn(VERSION_WARNING_MESSAGE)

        index = haystack.connections[self.connection_alias].get_unified_index()
        content_field = index.document_field

        if query_string == '*:*':
            kwargs = {
                'query': {
                    "match_all": {}
                },
            }
        else:
            kwargs = {
                'query': {
                    'query_string': {
                        'default_field': content_field,
                        'default_operator': DEFAULT_OPERATOR,
                        'query': query_string,
                        'analyze_wildcard': True,
                        'auto_generate_phrase_queries': True,
                        'fuzzy_min_sim': haystack.constants.FUZZY_MIN_SIM,
                        'fuzzy_max_expansions': haystack.constants.FUZZY_MAX_EXPANSIONS,
                    },
                },
            }

        # so far, no filters
        filters = []

        if fields:
            if isinstance(fields, (list, set)):
                fields = " ".join(fields)

            kwargs['fields'] = fields

        if sort_by is not None:
            order_list = []
            for field, direction in sort_by:
                if field == 'distance' and distance_point:
                    # Do the geo-enabled sort.
                    lng, lat = distance_point['point'].get_coords()
                    sort_kwargs = {
                        "_geo_distance": {
                            distance_point['field']: [lng, lat],
                            "order": direction,
                            "unit": "km"
                        }
                    }
                else:
                    if field == 'distance':
                        warnings.warn("In order to sort by distance, you must call the '.distance(...)' method.")

                    # Regular sorting.
                    sort_kwargs = {field: {'order': direction}}

                order_list.append(sort_kwargs)

            kwargs['sort'] = order_list

        # From/size offsets don't seem to work right in Elasticsearch's DSL. :/
        # if start_offset is not None:
        #     kwargs['from'] = start_offset

        # if end_offset is not None:
        #     kwargs['size'] = end_offset - start_offset

        if highlight is True:
            kwargs['highlight'] = {
                'fields': {
                    content_field: {'store': 'yes'},
                }
            }

        if self.include_spelling:
            kwargs['suggest'] = {
                'suggest': {
                    'text': spelling_query or query_string,
                    'term': {
                        # Using content_field here will result in suggestions of stemmed words.
                        'field': '_all',
                    },
                },
            }

        if narrow_queries is None:
            narrow_queries = set()

        if facets is not None:
            kwargs.setdefault('facets', {})

            for facet_fieldname, extra_options in facets.items():
                facet_options = {
                    'terms': {
                        'field': facet_fieldname,
                        'size': 100,
                    },
                }
                # Special cases for options applied at the facet level (not the terms level).
                if extra_options.pop('global_scope', False):
                    # Renamed "global_scope" since "global" is a python keyword.
                    facet_options['global'] = True
                if 'facet_filter' in extra_options:
                    facet_options['facet_filter'] = extra_options.pop('facet_filter')
                facet_options['terms'].update(extra_options)
                kwargs['facets'][facet_fieldname] = facet_options

        if date_facets is not None:
            kwargs.setdefault('facets', {})

            for facet_fieldname, value in date_facets.items():
                # Need to detect on gap_by & only add amount if it's more than one.
                interval = value.get('gap_by').lower()

                # Need to detect on amount (can't be applied on months or years).
                if value.get('gap_amount', 1) != 1 and interval not in ('month', 'year'):
                    # Just the first character is valid for use.
                    interval = "%s%s" % (value['gap_amount'], interval[:1])

                kwargs['facets'][facet_fieldname] = {
                    'date_histogram': {
                        'field': facet_fieldname,
                        'interval': interval,
                    },
                    'facet_filter': {
                        "range": {
                            facet_fieldname: {
                                'from': self._from_python(value.get('start_date')),
                                'to': self._from_python(value.get('end_date')),
                            }
                        }
                    }
                }

        if query_facets is not None:
            kwargs.setdefault('facets', {})

            for facet_fieldname, value in query_facets:
                kwargs['facets'][facet_fieldname] = {
                    'query': {
                        'query_string': {
                            'query': value,
                        }
                    },
                }

        if limit_to_registered_models is None:
            limit_to_registered_models = getattr(settings, 'HAYSTACK_LIMIT_TO_REGISTERED_MODELS', True)

        if models and len(models):
            model_choices = sorted(get_model_ct(model) for model in models)
        elif limit_to_registered_models:
            # Using narrow queries, limit the results to only models handled
            # with the current routers.
            model_choices = self.build_models_list()
        else:
            model_choices = []

        if len(model_choices) > 0:
            filters.append({"terms": {DJANGO_CT: model_choices}})

        for q in narrow_queries:
            filters.append({
                'fquery': {
                    'query': {
                        'query_string': {
                            'query': q
                        },
                    },
                    '_cache': True,
                }
            })

        if within is not None:
            from haystack.utils.geo import generate_bounding_box

            ((south, west), (north, east)) = generate_bounding_box(within['point_1'], within['point_2'])
            within_filter = {
                "geo_bounding_box": {
                    within['field']: {
                        "top_left": {
                            "lat": north,
                            "lon": west
                        },
                        "bottom_right": {
                            "lat": south,
                            "lon": east
                        }
                    }
                },
            }
            filters.append(within_filter)

        if dwithin is not None:
            lng, lat = dwithin['point'].get_coords()

            # NB: the 1.0.0 release of elasticsearch introduce an
            #     incompatible change on the distance filter formating
            if elasticsearch.VERSION >= (1, 0, 0):
                distance = "%(dist).6f%(unit)s" % {
                        'dist': dwithin['distance'].km,
                        'unit': "km"
                    }
            else:
                distance = dwithin['distance'].km

            dwithin_filter = {
                "geo_distance": {
                    "distance": distance,
                    dwithin['field']: {
                        "lat": lat,
                        "lon": lng
                    }
                }
            }
            filters.append(dwithin_filter)

        # if we want to filter, change the query type to filteres
        if filters:
            kwargs["query"] = {"filtered": {"query": kwargs.pop("query")}}
            if len(filters) == 1:
                kwargs['query']['filtered']["filter"] = filters[0]
            else:
                kwargs['query']['filtered']["filter"] = {"bool": {"must": filters}}

        return kwargs


class FuzzyElasticsearchSearchQuery(ElasticsearchSearchQuery):
    def build_query_fragment(self, field, filter_type, value):
        if haystack.__version__ > WARN_AFTER_VERSION:
            warnings.warn(VERSION_WARNING_MESSAGE)

        from haystack import connections
        query_frag = ''

        if not hasattr(value, 'input_type_name'):
            # Handle when we've got a ``ValuesListQuerySet``...
            if hasattr(value, 'values_list'):
                value = list(value)

            if isinstance(value, six.string_types):
                # It's not an ``InputType``. Assume ``Clean``.
                value = Clean(value)
            else:
                value = PythonData(value)

        # Prepare the query using the InputType.
        prepared_value = value.prepare(self)

        if not isinstance(prepared_value, (set, list, tuple)):
            # Then convert whatever we get back to what pysolr wants if needed.
            prepared_value = self.backend._from_python(prepared_value)

        # 'content' is a special reserved word, much like 'pk' in
        # Django's ORM layer. It indicates 'no special field'.
        if field == 'content':
            index_fieldname = ''
        else:
            index_fieldname = u'%s:' % connections[self._using].get_unified_index().get_index_fieldname(field)

        filter_types = {
            'contains': u'%s',
            'startswith': u'%s*',
            'exact': u'%s',
            'gt': u'{%s TO *}',
            'gte': u'[%s TO *]',
            'lt': u'{* TO %s}',
            'lte': u'[* TO %s]',
            'fuzzy': u'%s~',
        }

        if value.post_process is False:
            query_frag = prepared_value
        else:
            if filter_type in ['contains', 'startswith', 'fuzzy']:
                if value.input_type_name == 'exact':
                    query_frag = prepared_value
                else:
                    # Iterate over terms & incorportate the converted form of each into the query.
                    terms = []

                    if isinstance(prepared_value, six.string_types):
                        for possible_value in prepared_value.split(' '):
                            terms.append(filter_types[filter_type] % self.backend._from_python(possible_value))
                    else:
                        terms.append(filter_types[filter_type] % self.backend._from_python(prepared_value))

                    if len(terms) == 1:
                        query_frag = terms[0]
                    else:
                        query_frag = u"(%s)" % " AND ".join(terms)
            elif filter_type == 'in':
                in_options = []

                for possible_value in prepared_value:
                    in_options.append(u'"%s"' % self.backend._from_python(possible_value))

                query_frag = u"(%s)" % " OR ".join(in_options)
            elif filter_type == 'range':
                start = self.backend._from_python(prepared_value[0])
                end = self.backend._from_python(prepared_value[1])
                query_frag = u'["%s" TO "%s"]' % (start, end)
            elif filter_type == 'exact':
                if value.input_type_name == 'exact':
                    query_frag = prepared_value
                else:
                    prepared_value = Exact(prepared_value).prepare(self)
                    query_frag = filter_types[filter_type] % prepared_value
            else:
                if value.input_type_name != 'exact':
                    prepared_value = Exact(prepared_value).prepare(self)

                query_frag = filter_types[filter_type] % prepared_value

        if len(query_frag) and not isinstance(value, Raw):
            if not query_frag.startswith('(') and not query_frag.endswith(')'):
                query_frag = "(%s)" % query_frag

        return u"%s%s" % (index_fieldname, query_frag)


class FuzzyElasticsearchSearchEngine(ElasticsearchSearchEngine):
    backend = FuzzyElasticsearchSearchBackend
    query = FuzzyElasticsearchSearchQuery
