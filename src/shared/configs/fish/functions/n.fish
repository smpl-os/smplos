function n --description 'Open editor (current dir if no args)'
    set -l ed (command -v $EDITOR; or echo micro)
    if test (count $argv) -eq 0
        $ed .
    else
        $ed $argv
    end
end
