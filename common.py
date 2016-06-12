import datetime
import numpy as np

from features import *
from sklearn.ensemble import RandomForestClassifier
from sklearn import decomposition

N_COMPONENTS = 10 # MAX 149

def load_destinations():
    result = {}
    data = open ('destinations.csv', 'r').readlines()
    for line in data[1:]:
        tokens = line.split(',')
        result[int(tokens[0])] = [float(x) for x in tokens[1:]]

    X = np.array([result[x] for x in result.keys()])
    pca = decomposition.PCA(n_components=N_COMPONENTS)
    pca.fit(X)
    X = pca.transform(X)
    for i, x in enumerate(result.keys()):
        result[x] = X[i].tolist()
        assert len(result[x]) == N_COMPONENTS
    return result

DESTINATIONS = load_destinations()

def get_destination_features(srch_destination_id, feature_num=N_COMPONENTS):
    default_destination = [0.0 for i in xrange(0, feature_num)]
    return DESTINATIONS.get(srch_destination_id, default_destination)[0:feature_num]

def date(dt_str):
    try:
        return datetime.datetime.strptime(dt_str, "%Y-%m-%d")  
    except ValueError as e:
        print "Non-fatal error: %s" % e
        return datetime.datetime.strptime("2015-01-01", "%Y-%m-%d")  

def parse_line(line, is_labeled, is_header=False):
    if line[-1] == '\n':
        line = line[:-1]
    tokens = line.split(",")
    if not is_header and is_labeled and int(tokens[18]) == 0:
        return (None, None)
    # Removing 'id'(0) from test
    if not is_labeled:
        tokens = tokens[1:]
    # Removing 'is_booking'(18), 'cnt'(19) fields that
    # are not available in test.
    else:
        tokens = tokens[0:18] + tokens[20:]
    # Getting label and deleting it from tokens
    label = None
    if is_labeled:
        label = tokens[21]
        tokens = tokens[:21] + tokens[22:]
    return (tokens, label)

def get_features(line, is_labeled=True):
    (tokens, label) = parse_line(line, is_labeled)
    if tokens is None:
        return None
    # One should use in this function only constants defined in features.py
    # like SRCH_CI, SRCH_CO, USER_LOCATION_COUNTRY, ... Please avoid 
    # referencing tokens directly as this is harmful for readability and
    # is error-prone.
    check_in = date(tokens[SRCH_CI])
    check_out = date(tokens[SRCH_CO])
    len_of_stay = int(check_out.strftime('%j')) - int(check_in.strftime('%j'))
    if len_of_stay < 0:
       len_of_stay += 365
    weekends = 0
    if (check_in.weekday() == 4 or check_in.weekday() == 5) and (len_of_stay < 4):
        weekends = 1
    extra_features = [len_of_stay, weekends,
                  int(check_in.strftime('%j')), int(check_out.strftime('%j')), 
                  int(check_in.month), int(check_out.month),
                  int(check_in.strftime('%W')), int(check_out.strftime('%W'))]
    extra_features += get_destination_features(int(tokens[SRCH_DESTINATION_ID]))
    # These are features that we will use as is:
    RAW_FEATURES = [
        SITE_NAME, 
        POSA_CONTINENT, 
        USER_LOCATION_COUNTRY, 
        USER_LOCATION_REGION,
        USER_LOCATION_CITY,
        ORIG_DESTINATION_DISTANCE,
        USER_ID,
        IS_MOBILE,
        IS_PACKAGE,
        CHANNEL,
        SRCH_ADULTS_CNT,
        SRCH_CHILDREN_CNT,
        SRCH_RM_CNT,
        SRCH_DESTINATION_ID,
        SRCH_DESTINATION_TYPE_ID,
        HOTEL_CONTINENT,
        HOTEL_COUNTRY,
        HOTEL_MARKET]
    features = [
        tokens[raw_feature_id]
        for raw_feature_id in RAW_FEATURES] + extra_features
    features = [
        float (f) if f != '' else 0.0 
        for f in features]
    return (features, label)

def load_dataset_from_file(filename, examples_count, is_labeled=True):
    data = open (filename, 'r').readlines()
    # Next two lines verifies that the parsing result of header is what
    # we expect.
    header, _unused = parse_line(data[0], is_labeled, is_header=True)
    assert header == EXPECTED_HEADER
    data_X = []
    data_y = []
    cnt = 0
    for line in data[1:]:
        cnt += 1
        if len(data_X) == examples_count:
            break
        parse_result = get_features(line, is_labeled)
        if parse_result == None:
            continue
        (features, label) = parse_result
        data_X.append(np.array(features))
        data_y.append(label)
        if len(data_X) % 100000 == 0:
            print "Processed %d rows, loaded %d examples." % (
                cnt, len(data_X))
    return (np.array(data_X), np.array(data_y) if is_labeled else None)

class FastRandomForest(RandomForestClassifier):
    """This black magic is needed since sklearn random forest 
       has memory issues at prediction time. It is a simple
       bufferization over predict_proba() to avoid memory overuse."""

    BLOCK_SIZE = 10000

    def _predict_proba(self, X):
        return super(FastRandomForest, self).predict_proba(X)

    def predict_proba(self, X):
        print "invoking fast predict_proba"
        ys = [
            self._predict_proba(X[i:i+self.BLOCK_SIZE])
            for i in xrange(0, len(X), self.BLOCK_SIZE)]
        return np.concatenate(ys)

    def score(self, X, y):
        print "invoking custom score"
        return self.map5(X, y)

    def map5(self, X, y):
        predicted_probability_distribution = self.predict_proba(X)
        return self._mean_average_precision(
            predicted_probability_distribution, self.classes_, y)

    def _mean_average_precision(self,
                                predicted_probability_distribution,
                                list_of_classes,
                                test_y):
        total_error = 0
        k = -1
        for row in predicted_probability_distribution:
            k += 1
            prob_of_target_class = 0
            place = 1
            assert len(list_of_classes) == len(row)
            for i in xrange(0, len(row)):
                if list_of_classes[i] == test_y[k]:
                    prob_of_target_class = row[i]
                    break
            for i in xrange(0, len(row)):
                if (row[i] > prob_of_target_class
                    or (row[i] == prob_of_target_class and list_of_classes[i] > test_y[k])):
                    place += 1
                    if place >= 6: break
            if place < 6:
                total_error += 1.0 / place
        return total_error / len(predicted_probability_distribution)
