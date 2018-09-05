import logging
from collections import OrderedDict
from django.contrib.gis.measure import D
from django.contrib.gis.geos import Point
from models import Organisation, Category, Keyword, \
    OrganisationIncorrectInformationReport, OrganisationRating
from rest_framework import serializers


class PointField(serializers.CharField):

    def to_representation(self, obj):
        return ','.join([obj.get_x(), obj.get_y()])

    def to_internal_value(self, data):
        lat, lng = data.split(',')
        try:
            lat = float(lat)
            lng = float(lng)
        except ValueError:
            raise serializers.ValidationError(
                u'A valid comma separated point field is required.')
        return Point(lng, lat, srid=4326)


class HomePageCategoryKeywordGroupingSerializer(serializers.ModelSerializer):
    keywords = serializers.StringRelatedField(source='filtered_keywords',
                                              many=True)

    class Meta:
        model = Category
        fields = ('name', 'keywords')


class KeywordSerializer(serializers.ModelSerializer):
    class Meta:
        model = Keyword


class SearchSerializer(serializers.Serializer):
    location = PointField(required=False)
    radius = serializers.IntegerField(required=False)
    place_name = serializers.CharField(required=False)
    search_term = serializers.CharField(required=False)
    country = serializers.CharField(required=False, min_length=2)
    categories = serializers.ListField(
        child=serializers.IntegerField(), required=False)

    def perform_search(self, sqs):
        radius = self.validated_data.get('radius')
        country = self.validated_data.get('country')
        location = self.validated_data.get('location')
        categories = self.validated_data.get('categories')
        search_term = self.validated_data.get('search_term')

        if search_term:
            query = {
                "match": {
                    "text": {
                        "query": search_term,
                        "fuzziness": "AUTO"
                    }
                }
            }
            sqs = sqs.custom_query(query)

        if categories:
            sqs = sqs.filter(categories__in=categories)

        if country:
            sqs = sqs.filter(country=country)

        if location:
            sqs = sqs.distance('location', location).order_by('distance')

            if radius:
                sqs = sqs.dwithin('location', location, D(km=radius))

        return sqs

    def load_search_results(self, sqs, limit=20):
        return self.perform_search(sqs).load_all()[:limit]

    def format_results(self, sqs):
        organisation_distance_tuples = []

        try:
            organisation_distance_tuples = [
                (
                    result.object,
                    result.distance
                    if hasattr(result, 'distance') else None
                )
                for result in sqs
            ]
        except AttributeError:
            logging.warn(
                'The ElasticSearch index is likely out of sync with'
                ' the database.'
                ' You should run the `rebuild_index` management command.'
            )

        for organisation, distance in organisation_distance_tuples:
            if distance is not None and distance.m != float("inf"):
                organisation.distance = '{0:.2f}km'.format(distance.km)

        if organisation_distance_tuples:
            services = zip(*organisation_distance_tuples)[0]
            return services
        return []


class OrganisationSummarySerializer(serializers.ModelSerializer):
    distance = serializers.CharField()

    class Meta:
        model = Organisation
        fields = ('id', 'name', 'address', 'keywords', 'distance')

    # Note: Strictly speaking nothing above this comment is required for the
    # serializer to work, however it helps Swagger to work out what the
    # response will look like

    def to_representation(self, instance):
        d = OrderedDict()

        d['id'] = instance.id
        d['name'] = instance.name
        d['address'] = instance.address
        d['keywords'] = [keyword.name for keyword in instance.keywords.all()]
        d['distance'] = instance.distance if hasattr(instance, 'distance')\
            else None

        return d


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        # Swagger does not deal well with NestedSerializer (ie: depth attr)
        # https://github.com/marcgibbons/django-rest-swagger/issues/398
        # Explicitly defining the descendant serializers would solve it
        model = Organisation
        depth = 1


class OrganisationIncorrectInformationReportSerializer(
        serializers.ModelSerializer):
    class Meta:
        model = OrganisationIncorrectInformationReport
        read_only_fields = ('organisation',)


class OrganisationRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganisationRating
        read_only_fields = ('organisation',)


class OrganisationSendSMSRequestSerializer(serializers.Serializer):
    # TODO: add validation for cell_number field
    # http://www.django-rest-framework.org/api-guide/serializers/#validation
    cell_number = serializers.CharField()
    organisation_url = serializers.URLField()
    your_name = serializers.CharField(required=False)


class OrganisationSendSMSResponseSerializer(serializers.Serializer):
    result = serializers.BooleanField()
