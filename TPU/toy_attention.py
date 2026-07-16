def matmul(a, b):
    rows = len(a)
    cols = len(b[0])
    inner = len(b)
    return [
        [sum(a[i][k] * b[k][j] for k in range(inner)) for j in range(cols)]
        for i in range(rows)
    ]


def transpose(matrix):
    return [list(row) for row in zip(*matrix)]


def scale(matrix, factor):
    return [[value * factor for value in row] for row in matrix]


def softmax_rows(matrix):
    e = 2.718281828459045
    result = []
    for row in matrix:
        max_value = max(row)
        exps = [e ** (value - max_value) for value in row]
        total = sum(exps)
        result.append([value / total for value in exps])
    return result


def print_matrix(name, matrix):
    print(f"\n{name}:")
    for row in matrix:
        print("  [" + ", ".join(f"{value:8.4f}" for value in row) + "]")


def main():
    # Three tiny 2D token embeddings.
    input_embeddings = [
        [1, 0],
        [0, 1],
        [1, 1],
    ]

    # Small hand-picked projection matrices. In a trained model, these are learned.
    w_q = [
        [1, 0],
        [0, 1],
    ]
    w_k = [
        [1, 0],
        [0, 1],
    ]
    w_v = [
        [0, 0],
        [0, 2],
    ]

    q = matmul(input_embeddings, w_q)
    k = matmul(input_embeddings, w_k)
    v = matmul(input_embeddings, w_v)

    qk_t_scores = matmul(q, transpose(k))
    scaled_scores = scale(qk_t_scores, 1.0 / (len(q[0]) ** 0.5))
    attention_weights = softmax_rows(scaled_scores)
    output = matmul(attention_weights, v)

    print_matrix("Input embeddings", input_embeddings)
    print_matrix("Q", q)
    print_matrix("K", k)
    print_matrix("V", v)
    print_matrix("QK^T attention scores", qk_t_scores)
    print_matrix("Scaled QK^T attention scores", scaled_scores)
    print_matrix("Softmax attention weights", attention_weights)
    print_matrix("Final output", output)


if __name__ == "__main__":
    main()
